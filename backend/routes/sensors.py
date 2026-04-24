"""
Sensor management API routes.
Provides CRUD operations for ESP32 devices and their sensors.
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify
from backend.database import db
from backend.constants import TZ_NAME

logger = logging.getLogger(__name__)

sensors_bp = Blueprint('sensors', __name__, url_prefix='/api/sensors')


def convert_timezone(timestamp_str):
    """Convert UTC timestamp to configured timezone."""
    if not timestamp_str:
        return timestamp_str
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        local_dt = dt.astimezone(ZoneInfo(TZ_NAME))
        return local_dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return timestamp_str


def register_routes(app):
    app.register_blueprint(sensors_bp)


SENSOR_TYPES = ['analog', 'digital', 'ds18b20', 'dht11', 'dht22', 'bme280', 'capacitive']


@sensors_bp.route('', methods=['GET'])
def get_sensors():
    esp32_id = request.args.get('esp32_id', type=int)
    shelf_id = request.args.get('shelf_id', type=int)
    with db() as database:
        query = '''
            SELECT s.*, e.name as esp32_name, r.name as rack_name, sh.name as shelf_name
            FROM esp32_sensors s 
            LEFT JOIN esp32_devices e ON s.esp32_id = e.id 
            LEFT JOIN racks r ON s.rack_id = r.id
            LEFT JOIN shelves sh ON s.shelf_id = sh.id
            WHERE 1=1
        '''
        params = []
        if esp32_id:
            query += ' AND s.esp32_id = ?'
            params.append(esp32_id)
        elif shelf_id:
            query += ' AND s.shelf_id = ?'
            params.append(shelf_id)
        
        query += ' ORDER BY e.name, s.pin_number' if not esp32_id and not shelf_id else ' ORDER BY s.pin_number'
        
        sensors = database.fetch_all(query, params)
        return jsonify([dict(s) for s in sensors])


@sensors_bp.route('', methods=['POST'])
def create_sensor():
    data = request.get_json()
    
    esp32_id = data.get('esp32_id')
    name = data.get('name', '').strip()
    sensor_type = data.get('sensor_type')
    pin_number = data.get('pin_number')
    pin_mode = data.get('pin_mode', 'INPUT')
    
    if not esp32_id:
        logger.warning("create_sensor: esp32_id required")
        return jsonify({'error': 'esp32_id required'}), 400
    if not name:
        logger.warning("create_sensor: name required")
        return jsonify({'error': 'name required'}), 400
    if not sensor_type:
        logger.warning("create_sensor: sensor_type required")
        return jsonify({'error': 'sensor_type required'}), 400
    if pin_number is None:
        logger.warning("create_sensor: pin_number required")
        return jsonify({'error': 'pin_number required'}), 400
    
    if sensor_type not in SENSOR_TYPES:
        logger.warning(f"create_sensor: invalid sensor_type {sensor_type}")
        return jsonify({'error': f'Invalid sensor_type. Must be one of: {", ".join(SENSOR_TYPES)}'}), 400
    
    try:
        pin_number = int(pin_number)
    except (ValueError, TypeError):
        logger.warning(f"create_sensor: invalid pin_number {pin_number}")
        return jsonify({'error': 'pin_number must be an integer'}), 400
    
    try:
        with db() as database:
            existing = database.fetch_one('''
                SELECT id FROM esp32_sensors WHERE esp32_id = ? AND pin_number = ?
            ''', (esp32_id, pin_number))
            if existing:
                logger.warning(f"create_sensor: pin {pin_number} already in use")
                return jsonify({'error': f'Pin {pin_number} already in use'}), 400
            
            cursor = database.execute('''
                INSERT INTO esp32_sensors (esp32_id, name, sensor_type, pin_number, pin_mode)
                VALUES (?, ?, ?, ?, ?)
            ''', (esp32_id, name, sensor_type, pin_number, pin_mode))
            database.commit()
            
            sensor = database.fetch_one('SELECT * FROM esp32_sensors WHERE id = ?', (cursor.lastrowid,))
            logger.info(f"Created sensor {name} on pin {pin_number}")
            return jsonify(dict(sensor)), 201
    except Exception as e:
        logger.error(f"create_sensor failed: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@sensors_bp.route('/<int:sensor_id>', methods=['GET'])
def get_sensor(sensor_id):
    with db() as database:
        sensor = database.fetch_one('''
            SELECT s.*, e.name as esp32_name, r.name as rack_name, sh.name as shelf_name
            FROM esp32_sensors s 
            LEFT JOIN esp32_devices e ON s.esp32_id = e.id 
            LEFT JOIN racks r ON s.rack_id = r.id
            LEFT JOIN shelves sh ON s.shelf_id = sh.id
            WHERE s.id = ?
        ''', (sensor_id,))
        if not sensor:
            return jsonify({'error': 'Sensor not found'}), 404
        return jsonify(dict(sensor))


@sensors_bp.route('/<int:sensor_id>', methods=['PUT'])
def update_sensor(sensor_id):
    data = request.get_json()
    
    with db() as database:
        sensor = database.fetch_one('SELECT * FROM esp32_sensors WHERE id = ?', (sensor_id,))
        if not sensor:
            return jsonify({'error': 'Sensor not found'}), 404
        
        updates = []
        params = []
        
        for field in ['name', 'sensor_type', 'pin_number', 'pin_mode', 'calibration_offset', 'calibration_scale', 'is_enabled', 'rack_id', 'shelf_id', 'reservoir_id']:
            if field in data:
                value = data[field]
                if field in ('calibration_offset', 'calibration_scale'):
                    value = float(value)
                elif field == 'is_enabled':
                    value = 1 if value else 0
                elif field in ('rack_id', 'shelf_id', 'reservoir_id'):
                    value = int(value) if value else None
                updates.append(f'{field} = ?')
                params.append(value)
        
        if updates:
            params.append(sensor_id)
            database.execute(f'UPDATE esp32_sensors SET {", ".join(updates)} WHERE id = ?', tuple(params))
            database.commit()
        
        updated = database.fetch_one('SELECT * FROM esp32_sensors WHERE id = ?', (sensor_id,))
        return jsonify(dict(updated))


@sensors_bp.route('/<int:sensor_id>', methods=['DELETE'])
def delete_sensor(sensor_id):
    with db() as database:
        sensor = database.fetch_one('SELECT id FROM esp32_sensors WHERE id = ?', (sensor_id,))
        if not sensor:
            return jsonify({'error': 'Sensor not found'}), 404
        
        database.execute('DELETE FROM esp32_sensors WHERE id = ?', (sensor_id,))
        database.commit()
        return jsonify({'success': True})


@sensors_bp.route('/esp32', methods=['GET'])
def get_esp32_devices():
    with db() as database:
        devices = database.fetch_all('''
            SELECT e.*, 
                   (SELECT COUNT(*) FROM esp32_sensors WHERE esp32_id = e.id) as sensor_count,
                   (SELECT COUNT(*) FROM esp32_sensors WHERE esp32_id = e.id AND is_enabled = 1) as active_sensors
            FROM esp32_devices e
            ORDER BY e.name
        ''')
        result = []
        for d in devices:
            dev = dict(d)
            if dev.get('last_seen'):
                dev['last_seen'] = convert_timezone(dev['last_seen'])
            result.append(dev)
        return jsonify(result)


@sensors_bp.route('/esp32', methods=['POST'])
def create_esp32_device():
    data = request.get_json()
    
    name = data.get('name', '').strip()
    ip_address = data.get('ip_address', '').strip()
    mac_address = data.get('mac_address', '').strip()
    
    if not name:
        return jsonify({'error': 'name required'}), 400
    
    with db() as database:
        if mac_address:
            existing = database.fetch_one('SELECT id FROM esp32_devices WHERE mac_address = ?', (mac_address,))
            if existing:
                return jsonify({'error': 'Device with this MAC already exists'}), 400
        
        cursor = database.execute('''
            INSERT INTO esp32_devices (name, ip_address, mac_address)
            VALUES (?, ?, ?)
        ''', (name, ip_address, mac_address))
        database.commit()
        
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (cursor.lastrowid,))
        return jsonify(dict(device)), 201


@sensors_bp.route('/esp32/<int:esp32_id>', methods=['PUT'])
def update_esp32_device(esp32_id):
    data = request.get_json()
    
    with db() as database:
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        updates = []
        params = []
        
        for field in ['name', 'ip_address', 'is_active', 'update_rate']:
            if field in data:
                value = data[field]
                if field == 'is_active':
                    value = 1 if value else 0
                elif field == 'update_rate':
                    value = int(value)
                    if value < 5: value = 5
                    if value > 3600: value = 3600
                updates.append(f'{field} = ?')
                params.append(value)
        
        if updates:
            params.append(esp32_id)
            database.execute(f'UPDATE esp32_devices SET {", ".join(updates)} WHERE id = ?', tuple(params))
            database.commit()
        
        updated = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        return jsonify(dict(updated))


@sensors_bp.route('/esp32/<int:esp32_id>', methods=['DELETE'])
def delete_esp32_device(esp32_id):
    with db() as database:
        device = database.fetch_one('SELECT id FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        database.execute('DELETE FROM esp32_sensors WHERE esp32_id = ?', (esp32_id,))
        database.execute('DELETE FROM esp32_devices WHERE id = ?', (esp32_id,))
        database.commit()
        return jsonify({'success': True})


@sensors_bp.route('/esp32/discover', methods=['POST'])
def discover_esp32():
    """Receive discovery ping from ESP32 devices on the network."""
    data = request.get_json() or {}
    
    device_name = data.get('device_name', 'Unknown ESP32')
    ip_address = request.remote_addr
    mac_address = data.get('mac_address', '')
    
    with db() as database:
        if mac_address:
            existing = database.fetch_one('''
                SELECT id, name, ip_address FROM esp32_devices WHERE mac_address = ?
            ''', (mac_address,))
            if existing:
                database.execute('''
                    UPDATE esp32_devices SET last_seen = CURRENT_TIMESTAMP, ip_address = ?, is_active = 1 WHERE id = ?
                ''', (ip_address, existing['id']))
                database.commit()
                return jsonify({'id': existing['id'], 'name': existing['name'], 'status': 'updated'})
        
        existing_by_ip = database.fetch_one('''
            SELECT id FROM esp32_devices WHERE ip_address = ?
        ''', (ip_address,))
        
        if existing_by_ip:
            database.execute('''
                UPDATE esp32_devices SET last_seen = CURRENT_TIMESTAMP, is_active = 1 WHERE id = ?
            ''', (existing_by_ip['id'],))
            database.commit()
            device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (existing_by_ip['id'],))
            return jsonify({'id': device['id'], 'name': device['name'], 'status': 'known'})
        
        cursor = database.execute('''
            INSERT INTO esp32_devices (name, ip_address, mac_address, is_active)
            VALUES (?, ?, ?, 1)
        ''', (device_name, ip_address, mac_address))
        database.commit()
        
        return jsonify({'id': cursor.lastrowid, 'name': device_name, 'status': 'new'}), 201


@sensors_bp.route('/esp32/<int:esp32_id>/config', methods=['GET'])
def get_esp32_config(esp32_id):
    with db() as database:
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        sensors = database.fetch_all('''
            SELECT name, sensor_type, pin_number, pin_mode, 
                   calibration_offset, calibration_scale
            FROM esp32_sensors 
            WHERE esp32_id = ? AND is_enabled = 1
            ORDER BY pin_number
        ''', (esp32_id,))
        
        wifi = database.fetch_one('''
            SELECT ssid, password FROM wifi_config WHERE is_default = 1 LIMIT 1
        ''')
        
        update_rate = device['update_rate'] if 'update_rate' in device.keys() else 30
        
        config = {
            'device_name': device['name'],
            'update_rate': update_rate,
            'sensors': [dict(s) for s in sensors]
        }
        
        if wifi:
            config['wifi'] = {
                'ssid': wifi['ssid'],
                'password': wifi['password']
            }
        
        return jsonify(config)


@sensors_bp.route('/esp32/<int:esp32_id>/readings', methods=['GET'])
def get_sensor_readings(esp32_id):
    """Get sensor readings for an ESP32 device."""
    limit = request.args.get('limit', 100, type=int)
    sensor_id = request.args.get('sensor_id', type=int)
    
    with db() as database:
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        if sensor_id:
            query = '''
                SELECT r.id, r.value, r.timestamp, s.name as sensor_name, s.sensor_type,
                       COALESCE(rk.name, 'Unassigned') as rack_name,
                       COALESCE(sh.name, 'Unassigned') as shelf_name
                FROM sensor_readings r
                LEFT JOIN esp32_sensors s ON r.sensor_id = s.id
                LEFT JOIN racks rk ON r.rack_id = rk.id
                LEFT JOIN shelves sh ON r.shelf_id = sh.id
                WHERE r.esp32_id = ? AND r.sensor_id = ?
                ORDER BY r.timestamp DESC
                LIMIT ?
            '''
            readings = database.fetch_all(query, (esp32_id, sensor_id, limit))
        else:
            query = '''
                SELECT r.id, r.value, r.timestamp, s.name as sensor_name, s.sensor_type,
                       COALESCE(rk.name, 'Unassigned') as rack_name,
                       COALESCE(sh.name, 'Unassigned') as shelf_name
                FROM sensor_readings r
                LEFT JOIN esp32_sensors s ON r.sensor_id = s.id
                LEFT JOIN racks rk ON r.rack_id = rk.id
                LEFT JOIN shelves sh ON r.shelf_id = sh.id
                WHERE r.esp32_id = ?
                ORDER BY r.timestamp DESC
                LIMIT ?
            '''
            readings = database.fetch_all(query, (esp32_id, limit))
        
        return jsonify([{
            'id': r['id'],
            'value': r['value'],
            'timestamp': convert_timezone(r['timestamp']),
            'sensor_name': r['sensor_name'] or 'Unknown',
            'sensor_type': r['sensor_type'] or 'unknown',
            'rack_name': r['rack_name'],
            'shelf_name': r['shelf_name']
        } for r in readings])


@sensors_bp.route('/esp32/<int:esp32_id>/latest', methods=['GET'])
def get_latest_readings(esp32_id):
    """Get latest reading for each sensor on an ESP32."""
    with db() as database:
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        readings = database.fetch_all('''
            SELECT r.id, r.value, r.timestamp, s.name as sensor_name, s.sensor_type, s.pin_number
            FROM sensor_readings r
            LEFT JOIN esp32_sensors s ON r.sensor_id = s.id
            WHERE r.esp32_id = ? AND r.id = (
                SELECT MAX(r2.id) FROM sensor_readings r2 WHERE r2.sensor_id = r.sensor_id
            )
            ORDER BY s.name
        ''', (esp32_id,))
        
        return jsonify([{
            'id': r['id'],
            'value': r['value'],
            'timestamp': convert_timezone(r['timestamp']),
            'sensor_name': r['sensor_name'] or 'Unknown',
            'sensor_type': r['sensor_type'] or 'unknown',
            'pin_number': r['pin_number']
        } for r in readings])


@sensors_bp.route('/readings/latest', methods=['GET'])
def get_all_latest_readings():
    """Get latest reading for all sensors across all ESP32 devices."""
    with db() as database:
        readings = database.fetch_all('''
            SELECT r.id, r.value, r.timestamp, 
                   COALESCE(s.name, 'Unknown') as sensor_name, 
                   COALESCE(s.sensor_type, 'unknown') as sensor_type, 
                   s.pin_number,
                   e.id as esp32_id, e.name as esp32_name
            FROM sensor_readings r
            INNER JOIN esp32_sensors s ON r.sensor_id = s.id
            JOIN esp32_devices e ON r.esp32_id = e.id
            WHERE r.id IN (
                SELECT MAX(r2.id) FROM sensor_readings r2 
                INNER JOIN esp32_sensors s2 ON r2.sensor_id = s2.id
                GROUP BY r2.sensor_id
            )
            ORDER BY e.name, s.pin_number
        ''')
        
        return jsonify([{
            'id': r['id'],
            'value': r['value'],
            'timestamp': convert_timezone(r['timestamp']),
            'sensor_name': r['sensor_name'] or 'Unknown',
            'sensor_type': r['sensor_type'] or 'unknown',
            'pin_number': r['pin_number'],
            'esp32_id': r['esp32_id'],
            'esp32_name': r['esp32_name'] or 'Unknown'
        } for r in readings])


@sensors_bp.route('/readings', methods=['GET'])
def get_all_readings():
    """Get all sensor readings across all ESP32 devices."""
    limit = request.args.get('limit', 500, type=int)
    
    with db() as database:
        readings = database.fetch_all('''
            SELECT r.id, r.value, r.timestamp, 
                   COALESCE(s.name, 'Unknown') as sensor_name, 
                   COALESCE(s.sensor_type, 'unknown') as sensor_type, 
                   s.pin_number,
                   e.id as esp32_id, e.name as esp32_name,
                   COALESCE(rk.name, 'Unassigned') as rack_name,
                   COALESCE(sh.name, 'Unassigned') as shelf_name
            FROM sensor_readings r
            LEFT JOIN esp32_sensors s ON r.sensor_id = s.id
            LEFT JOIN esp32_devices e ON r.esp32_id = e.id
            LEFT JOIN racks rk ON r.rack_id = rk.id
            LEFT JOIN shelves sh ON r.shelf_id = sh.id
            ORDER BY r.timestamp DESC
            LIMIT ?
        ''', (limit,))
        
        return jsonify([{
            'id': r['id'],
            'value': r['value'],
            'timestamp': convert_timezone(r['timestamp']),
            'sensor_name': r['sensor_name'] or 'Unknown',
            'sensor_type': r['sensor_type'] or 'unknown',
            'pin_number': r['pin_number'],
            'esp32_id': r['esp32_id'],
            'esp32_name': r['esp32_name'] or 'Unknown',
            'rack_name': r['rack_name'],
            'shelf_name': r['shelf_name']
        } for r in readings])


@sensors_bp.route('/wifi', methods=['GET'])
def get_wifi_configs():
    """Get all WiFi configurations."""
    with db() as database:
        configs = database.fetch_all('SELECT id, ssid, is_default, created_at FROM wifi_config ORDER BY is_default DESC, ssid')
        return jsonify([dict(c) for c in configs])


@sensors_bp.route('/esp32/<int:esp32_id>/sensors', methods=['POST'])
def receive_sensors_from_esp32(esp32_id):
    """Receive sensor configuration from ESP32 device."""
    data = request.get_json()
    
    with db() as database:
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        sensors = data.get('sensors', [])
        created = 0
        
        for s in sensors:
            name = s.get('name', '').strip()
            sensor_type = s.get('sensor_type', 'analog')
            pin_number = s.get('pin_number')
            
            if not name or pin_number is None:
                continue
            
            existing = database.fetch_one('''
                SELECT id FROM esp32_sensors WHERE esp32_id = ? AND pin_number = ?
            ''', (esp32_id, pin_number))
            
            if not existing:
                database.execute('''
                    INSERT INTO esp32_sensors (esp32_id, name, sensor_type, pin_number, pin_mode)
                    VALUES (?, ?, ?, ?, 'INPUT')
                ''', (esp32_id, name, sensor_type, pin_number))
                created += 1
        
        database.commit()
        return jsonify({'status': 'ok', 'created': created, 'total': len(sensors)}), 201


@sensors_bp.route('/esp32/<int:esp32_id>/pull', methods=['POST'])
def pull_sensors_from_esp32(esp32_id):
    """Pull sensor configuration from ESP32 device."""
    import requests
    
    with db() as database:
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        ip_address = device['ip_address']
        if not ip_address:
            return jsonify({'error': 'No IP address for device'}), 400
        
        try:
            logger.info(f"Pulling sensors from ESP32 at {ip_address}")
            response = requests.get(f'http://{ip_address}:80/api/sensors/list', timeout=5)
            response.raise_for_status()
            data = response.json()
            
            sensors = data.get('sensors', [])
            created = 0
            
            for s in sensors:
                name = s.get('name', '').strip()
                sensor_type = s.get('sensor_type', 'analog')
                pin_number = s.get('pin_number')
                
                if not name or pin_number is None:
                    continue
                
                existing = database.fetch_one('''
                    SELECT id FROM esp32_sensors WHERE esp32_id = ? AND pin_number = ?
                ''', (esp32_id, pin_number))
                
                if existing:
                    database.execute('''
                        UPDATE esp32_sensors SET name = ?, sensor_type = ? WHERE id = ?
                    ''', (name, sensor_type, existing['id']))
                    created += 1
                else:
                    database.execute('''
                        INSERT INTO esp32_sensors (esp32_id, name, sensor_type, pin_number, pin_mode)
                        VALUES (?, ?, ?, ?, 'INPUT')
                    ''', (esp32_id, name, sensor_type, pin_number))
                    created += 1
            
            database.commit()
            logger.info(f"Pulled {created} sensors from ESP32")
            return jsonify({'status': 'ok', 'pulled': created, 'total': len(sensors)})
        except requests.RequestException as e:
            logger.error(f"Failed to pull sensors from ESP32: {e}")
            return jsonify({'error': f'Failed to connect to ESP32: {str(e)}'}), 500
        except Exception as e:
            logger.error(f"Unexpected error pulling sensors: {e}")
            return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@sensors_bp.route('/esp32/<int:esp32_id>/push', methods=['POST'])
def push_sensors_to_esp32(esp32_id):
    """Push sensor configuration to ESP32 device."""
    import requests
    
    with db() as database:
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        ip_address = device['ip_address']
        if not ip_address:
            return jsonify({'error': 'No IP address for device'}), 400
        
        update_rate = device['update_rate'] if 'update_rate' in device.keys() else 30
        
        sensors = database.fetch_all('''
            SELECT name, sensor_type, pin_number, pin_mode,
                   calibration_offset, calibration_scale
            FROM esp32_sensors
            WHERE esp32_id = ? AND is_enabled = 1
            ORDER BY pin_number
        ''', (esp32_id,))
        
        sensor_list = []
        for s in sensors:
            sensor_list.append({
                'name': s['name'],
                'sensor_type': s['sensor_type'],
                'pin_number': s['pin_number'],
                'calibration_offset': s['calibration_offset'],
                'calibration_scale': s['calibration_scale']
            })
        
        config_payload = {
            'device_name': device['name'],
            'update_rate': update_rate,
            'sensors': sensor_list
        }
        
        try:
            logger.info(f"Pushing to ESP32 {ip_address}: {config_payload}")
            response = requests.post(
                f'http://{ip_address}:80/api/sensors/config',
                json=config_payload,
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )
            logger.info(f"Response: {response.status_code} {response.text}")
            response.raise_for_status()
            return jsonify({'status': 'ok', 'pushed': len(sensor_list)})
        except requests.RequestException as e:
            logger.error(f"Push failed: {e}")
            return jsonify({'error': f'Failed to push to ESP32: {str(e)}'}), 500


@sensors_bp.route('/esp32/<int:esp32_id>/trigger', methods=['POST'])
def trigger_esp32_reading(esp32_id):
    """Trigger an ESP32 to send a reading immediately."""
    import requests
    
    with db() as database:
        device = database.fetch_one('SELECT * FROM esp32_devices WHERE id = ?', (esp32_id,))
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        
        ip_address = device['ip_address']
        if not ip_address:
            return jsonify({'error': 'No IP address for device'}), 400
        
        try:
            response = requests.post(
                f'http://{ip_address}:80/api/sensors/trigger',
                timeout=10
            )
            response.raise_for_status()
            return jsonify({'status': 'ok', 'message': 'Trigger sent to ESP32'})
        except requests.RequestException as e:
            return jsonify({'error': f'Failed to trigger ESP32: {str(e)}'}), 500


@sensors_bp.route('/wifi', methods=['POST'])
def create_wifi_config():
    data = request.get_json()
    
    ssid = data.get('ssid', '').strip()
    password = data.get('password', '').strip()
    is_default = data.get('is_default', False)
    
    if not ssid or not password:
        return jsonify({'error': 'ssid and password required'}), 400
    
    with db() as database:
        existing = database.fetch_one('SELECT id FROM wifi_config WHERE ssid = ?', (ssid,))
        if existing:
            return jsonify({'error': 'WiFi network already exists'}), 400
        
        cursor = database.execute('''
            INSERT INTO wifi_config (ssid, password, is_default)
            VALUES (?, ?, ?)
        ''', (ssid, password, 1 if is_default else 0))
        database.commit()
        
        if is_default:
            database.execute('UPDATE wifi_config SET is_default = 0 WHERE id != ?', (cursor.lastrowid,))
            database.commit()
        
        return jsonify({'id': cursor.lastrowid, 'ssid': ssid, 'is_default': is_default}), 201


@sensors_bp.route('/wifi/<int:wifi_id>', methods=['PUT'])
def update_wifi_config(wifi_id):
    data = request.get_json()
    
    ssid = data.get('ssid', '').strip()
    password = data.get('password', '').strip()
    is_default = data.get('is_default')
    
    if not ssid or not password:
        return jsonify({'error': 'ssid and password required'}), 400
    
    with db() as database:
        database.execute('''
            UPDATE wifi_config SET ssid = ?, password = ? WHERE id = ?
        ''', (ssid, password, wifi_id))
        
        if is_default:
            database.execute('UPDATE wifi_config SET is_default = 0 WHERE id != ?', (wifi_id,))
        
        database.commit()
        return jsonify({'status': 'ok'})


@sensors_bp.route('/wifi/<int:wifi_id>', methods=['DELETE'])
def delete_wifi_config(wifi_id):
    with db() as database:
        database.execute('DELETE FROM wifi_config WHERE id = ?', (wifi_id,))
        database.commit()
        return jsonify({'status': 'ok'})


@sensors_bp.route('/wifi/default/<int:wifi_id>', methods=['POST'])
def set_default_wifi(wifi_id):
    with db() as database:
        database.execute('UPDATE wifi_config SET is_default = 0')
        database.execute('UPDATE wifi_config SET is_default = 1 WHERE id = ?', (wifi_id,))
        database.commit()
        return jsonify({'status': 'ok'})


@sensors_bp.route('/readings', methods=['POST'])
def log_sensor_reading():
    """Receive and log sensor readings from ESP32 devices."""
    data = request.get_json()
    
    if data is None:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    esp32_id = data.get('esp32_id')
    if not esp32_id:
        device_ip = data.get('device')
        if device_ip:
            with db() as database:
                dev = database.fetch_one('SELECT id FROM esp32_devices WHERE ip_address = ?', (device_ip,))
                if dev:
                    esp32_id = dev['id']
    
    readings = data.get('readings', [])
    
    if isinstance(readings, list) and len(readings) > 0:
        for r in readings:
            sensor_name = r.get('sensor')
            value = r.get('value')
            _log_single_reading(sensor_name, value, esp32_id)
    else:
        sensor_name = data.get('sensor')
        value = data.get('value')
        _log_single_reading(sensor_name, value, esp32_id)
    
    return jsonify({'status': 'ok', 'count': len(readings) if isinstance(readings, list) else 1})


def _log_single_reading(sensor_name, value, esp32_id=None):
    if not sensor_name or value is None:
        return
    
    try:
        value = float(value)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid sensor value '{value}': {e}")
        return
    
    try:
        with db() as database:
            query = '''
                SELECT s.id, s.esp32_id, s.rack_id, s.shelf_id, e.name as esp32_name
                FROM esp32_sensors s
                JOIN esp32_devices e ON s.esp32_id = e.id
                WHERE s.name = ? COLLATE NOCASE
            '''
            params = [sensor_name]
            if esp32_id:
                query += ' AND s.esp32_id = ?'
                params.append(esp32_id)
            
            sensor = database.fetch_one(query, params)
            
            if not sensor:
                logger.warning(f"Sensor not found: {sensor_name}")
                return
            
            sensor_dict = dict(sensor)
            esp32_id = sensor_dict['esp32_id']
            sensor_id = sensor_dict['id']
            rack_id = sensor_dict.get('rack_id')
            shelf_id = sensor_dict.get('shelf_id')
            
            database.execute('''
                INSERT INTO sensor_readings (esp32_id, sensor_id, value, rack_id, shelf_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (esp32_id, sensor_id, value, rack_id, shelf_id))
            database.commit()
            
            database.execute('''
                UPDATE esp32_devices SET last_seen = CURRENT_TIMESTAMP WHERE id = ?
            ''', (esp32_id,))
            database.commit()
    except Exception as e:
        logger.error(f"Failed to log sensor reading for {sensor_name}: {e}")