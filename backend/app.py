import os
import json
import asyncio
import logging
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import sqlite3
from kasa import Discover, Credentials
from cryptography.fernet import Fernet
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(filename='/data/app.log', level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

app = Flask(__name__, static_folder='../frontend', template_folder='../frontend')
CORS(app)

scheduler = BackgroundScheduler()

DB_PATH = '/data/devices.db'
ENCRYPTION_KEY_FILE = '/data/encryption.key'

PROVIDERS = ['kasa', 'tapo']

def run_async(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(func(*args, **kwargs))
        finally:
            loop.close()
    return wrapper

def get_encryption_key():
    key_path = ENCRYPTION_KEY_FILE
    if os.path.exists(key_path):
        with open(key_path, 'rb') as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        os.makedirs('/data', exist_ok=True)
        with open(key_path, 'wb') as f:
            f.write(key)
        return key

def encrypt_value(value):
    if not value:
        return None
    key = get_encryption_key()
    f = Fernet(key)
    return f.encrypt(value.encode()).decode()

def decrypt_value(encrypted_value):
    if not encrypted_value:
        return None
    key = get_encryption_key()
    f = Fernet(key)
    return f.decrypt(encrypted_value.encode()).decode()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'kasa',
            username_encrypted TEXT,
            password_encrypted TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            name TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            mac_address TEXT,
            model TEXT,
            child_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_id) REFERENCES accounts(id)
        )
    ''')
    try:
        conn.execute('ALTER TABLE devices ADD COLUMN child_id TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE devices ADD COLUMN is_on INTEGER DEFAULT 0')
    except:
        pass
    conn.execute('''
        CREATE TABLE IF NOT EXISTS racks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS shelves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rack_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rack_id) REFERENCES racks(id) ON DELETE CASCADE
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reservoirs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rack_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rack_id) REFERENCES racks(id) ON DELETE CASCADE
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_type TEXT NOT NULL,
            parent_id INTEGER NOT NULL,
            device_id INTEGER,
            component_type TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        conn.execute('ALTER TABLE components ADD COLUMN device_id INTEGER REFERENCES devices(id)')
    except:
        pass
    conn.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'on',
            hour INTEGER NOT NULL,
            minute INTEGER NOT NULL,
            days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()

def get_account_credentials(account_id):
    conn = get_db()
    account = conn.execute('SELECT * FROM accounts WHERE id = ?', (account_id,)).fetchone()
    conn.close()
    if not account:
        return None
    if account['provider'] == 'kasa' or account['provider'] == 'tapo':
        username = decrypt_value(account['username_encrypted'])
        password = decrypt_value(account['password_encrypted'])
        if username and password:
            return Credentials(username=username, password=password)
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/providers', methods=['GET'])
def get_providers():
    return jsonify(PROVIDERS)

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    conn = get_db()
    accounts = conn.execute('SELECT id, name, provider, created_at FROM accounts ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(row) for row in accounts])

@app.route('/api/accounts', methods=['POST'])
def create_account():
    data = request.get_json()
    name = data.get('name')
    provider = data.get('provider', 'kasa')
    username = data.get('username')
    password = data.get('password')

    if not name or not provider:
        return jsonify({'error': 'Name and provider required'}), 400

    if provider not in PROVIDERS:
        return jsonify({'error': f'Provider must be one of: {PROVIDERS}'}), 400

    username_enc = encrypt_value(username)
    password_enc = encrypt_value(password)

    conn = get_db()
    conn.execute(
        'INSERT INTO accounts (name, provider, username_encrypted, password_encrypted) VALUES (?, ?, ?, ?)',
        (name, provider, username_enc, password_enc)
    )
    conn.commit()
    account_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()

    return jsonify({'id': account_id, 'name': name, 'provider': provider})

@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
def delete_account(account_id):
    conn = get_db()
    conn.execute('DELETE FROM devices WHERE account_id = ?', (account_id,))
    conn.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/devices/refresh', methods=['POST'])
def refresh_devices():
    account_id = request.json.get('account_id') if request.is_json else None
    conn = get_db()

    if account_id:
        devices = conn.execute('SELECT * FROM devices WHERE account_id = ?', (account_id,)).fetchall()
    else:
        devices = conn.execute('SELECT * FROM devices').fetchall()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for device in devices:
        if device['account_id'] and device['ip_address']:
            creds = get_account_credentials(device['account_id'])
            try:
                state = loop.run_until_complete(_get_device_state(creds, device['ip_address'], device['child_id']))
                if state is not None:
                    conn.execute('UPDATE devices SET is_on = ? WHERE id = ?', (state, device['id']))
            except Exception as e:
                logging.error(f"Refresh error for device {device['id']}: {e}")

    conn.commit()
    loop.close()
    return jsonify({'success': True})

@app.route('/api/devices', methods=['GET'])
def get_devices():
    account_id = request.args.get('account_id', type=int)
    conn = get_db()
    if account_id:
        devices = conn.execute('SELECT * FROM devices WHERE account_id = ? ORDER BY created_at DESC', (account_id,)).fetchall()
    else:
        devices = conn.execute('SELECT * FROM devices ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(row) for row in devices])

@app.route('/api/devices/discover', methods=['POST'])
@run_async
async def discover_devices():
    account_id = request.json.get('account_id') if request.is_json else None

    disc = Discover()
    found_devices = await disc.discover()
    result = {}
    for ip, dev in found_devices.items():
        if dev:
            result[ip] = {
                'ip': ip,
                'mac': dev.mac,
                'model': dev.model
            }

    conn = get_db()
    conn.close()
    return jsonify(result)

@app.route('/api/devices', methods=['POST'])
@run_async
async def add_device():
    data = request.get_json()
    ip = data.get('ip_address')
    account_id = data.get('account_id')

    if not ip:
        return jsonify({'error': 'IP address required'}), 400

    credentials = get_account_credentials(account_id) if account_id else None

    # Primary discovery – this populates plug.children
    try:
        plug = await Discover.discover_single(ip, credentials=credentials)
        await plug.update()
    except Exception as e:
        # Fallback only if primary fails – still try to get children on primary port afterwards
        try:
            plug = await Discover.discover_single(ip, credentials=credentials, port=9999)
            await plug.update()
        except Exception as e2:
            logging.error(f"Error getting device info for {ip}: {e}, fallback also failed: {e2}")
            plug = None

    if not plug:
        return jsonify({'error': 'Unable to discover device'}), 500

    # Ensure we have a children list (populated from primary discovery)
    children = getattr(plug, 'children', [])
    if not children:
        # Try once more on the normal port to get children information
        try:
            temp = await Discover.discover_single(ip, credentials=credentials)
            await temp.update()
            children = getattr(temp, 'children', [])
        except Exception:
            pass

    # Build device payload: parent + all children
    parent_dev = {
        'name': plug.alias or 'Smart Outlet',
        'mac_address': plug.mac,
        'model': plug.model,
        'child_id': None,
    }

    child_devs = []
    for child in children:
        child_devs.append({
            'name': child.alias or f'Child {child.device_id}',
            'mac_address': child.mac,
            'model': child.model,
            'child_id': child.device_id,
        })

    device_payload = [parent_dev] + child_devs

    # Insert each device into the DB
    conn = get_db()
    added_ids = []
    for dev in device_payload:
        try:
            conn.execute(
                'INSERT INTO devices (account_id, name, ip_address, mac_address, model, child_id) '
                'VALUES (?,?,?,?,?,?)',
                (account_id, dev['name'], ip, dev['mac_address'], dev['model'], dev.get('child_id'))
            )
            conn.commit()
            new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            added_ids.append({'id': new_id, 'name': dev['name'], 'ip_address': ip})
        except sqlite3.IntegrityError:
            pass
    conn.close()

    # Create component rows linking each child to its parent entry
    for child in child_devs:
        conn.execute(
            'INSERT INTO components (parent_type, parent_id, device_id, component_type, name) '
            'VALUES (?,?,?,?,"Child device")',
            ('device', child['child_id'], child['child_id'], 'pump')
        )
    conn.commit()
    conn.close()

    if not added_ids:
        return jsonify({'error': 'Device already exists'}), 400

    return jsonify(added_ids)

@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
def delete_device(device_id):
    conn = get_db()
    conn.execute('DELETE FROM devices WHERE id = ?', (device_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/devices/<int:device_id>', methods=['PUT'])
def update_device(device_id):
    data = request.get_json()
    name = data.get('name')

    conn = get_db()
    conn.execute('UPDATE devices SET name = ? WHERE id = ?', (name, device_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

async def _get_device_state(credentials, parent_ip, child_id):
    for attempt in range(3):
        try:
            try:
                from kasa.transports.klaptransport import KlapTransportV2
                from kasa.protocols import IotProtocol
                from kasa.iot import IotStrip
                from kasa.deviceconfig import DeviceConfig

                config = DeviceConfig(host=parent_ip, credentials=credentials)
                protocol = IotProtocol(transport=KlapTransportV2(config=config))
                plug = IotStrip(host=parent_ip, protocol=protocol)
                await plug.update()
            except Exception as e:
                logging.error(f"Attempt {attempt+1}: Error getting state with V2: {e}")
                await asyncio.sleep(2)
                plug = await Discover.discover_single(parent_ip, credentials=credentials, port=9999)
                await plug.update()
            
            if child_id:
                for child in plug.children or []:
                    if child.device_id == child_id:
                        await child.update()
                        return child.is_on
                return None
            else:
                return plug.is_on
        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed getting state: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
                continue
            return None
    
    return None

async def _toggle_device_state(credentials, parent_ip, child_id, desired_state=None):
    def do_toggle(plug, child_id):
        for child in plug.children or []:
            if child.device_id == child_id:
                return child
        return None

    for attempt in range(3):
        try:
            try:
                from kasa.transports.klaptransport import KlapTransportV2
                from kasa.protocols import IotProtocol
                from kasa.iot import IotStrip
                from kasa.deviceconfig import DeviceConfig

                config = DeviceConfig(host=parent_ip, credentials=credentials)
                protocol = IotProtocol(transport=KlapTransportV2(config=config))
                plug = IotStrip(host=parent_ip, protocol=protocol)
                await plug.update()
            except Exception as e:
                logging.error(f"Attempt {attempt+1}: Error toggling with V2: {e}")
                await asyncio.sleep(2)
                plug = await Discover.discover_single(parent_ip, credentials=credentials, port=9999)
                await plug.update()

            if child_id:
                child = do_toggle(plug, child_id)
                if child:
                    await child.update()
                    if desired_state is not None:
                        if desired_state:
                            await child.turn_on()
                        else:
                            await child.turn_off()
                    else:
                        await child.turn_on() if not child.is_on else await child.turn_off()
                    await asyncio.sleep(1)
                    await plug.update()
                    for c in plug.children:
                        if c.device_id == child_id:
                            return c.is_on
                return None
            else:
                if desired_state is not None:
                    if desired_state:
                        await plug.turn_on()
                    else:
                        await plug.turn_off()
                else:
                    await plug.toggle()
                await plug.update()
                return plug.is_on
                await plug.update()
                return plug.is_on
        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
                continue
            return None
    
    return None

@app.route('/api/devices/<int:device_id>/toggle', methods=['POST'])
@run_async
async def toggle_device(device_id):
    conn = get_db()
    device = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    account_id = device['account_id'] if device else None
    child_id = device['child_id'] if device else None
    parent_ip = device['ip_address'] if device else None
    conn.close()

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    credentials = get_account_credentials(account_id) if account_id else None
    logging.info(f"Toggling device {device_id} ({device['name']})")
    state = await _toggle_device_state(credentials, parent_ip, child_id)
    logging.info(f"Device {device_id} toggled to {'ON' if state else 'OFF'}")

    if state is None:
        return jsonify({'error': 'Failed to toggle device'}), 500

    return jsonify({'is_on': state})

@app.route('/api/devices/<int:device_id>/state', methods=['GET'])
@run_async
async def get_device_state(device_id):
    conn = get_db()
    device = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    account_id = device['account_id'] if device else None
    child_id = device['child_id'] if device else None
    parent_ip = device['ip_address'] if device else None
    conn.close()

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    credentials = get_account_credentials(account_id) if account_id else None
    state = await _get_device_state(credentials, parent_ip, child_id)

    if state is None:
        return jsonify({'is_on': None, 'error': 'Device unreachable'})

    return jsonify({'is_on': state})

@app.route('/api/racks', methods=['GET'])
def get_racks():
    conn = get_db()
    racks = conn.execute('SELECT * FROM racks ORDER BY is_default DESC, name').fetchall()
    result = []
    for rack in racks:
        result.append(dict(rack))
    conn.close()
    return jsonify(result)

@app.route('/api/racks/default/<int:rack_id>', methods=['POST'])
def set_default_rack(rack_id):
    conn = get_db()
    conn.execute('UPDATE racks SET is_default = 0')
    conn.execute('UPDATE racks SET is_default = 1 WHERE id = ?', (rack_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/racks', methods=['POST'])
def create_rack():
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({'error': 'Name required'}), 400
    conn = get_db()
    conn.execute('INSERT INTO racks (name) VALUES (?)', (name,))
    conn.commit()
    rack_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': rack_id, 'name': name})

@app.route('/api/racks/<int:rack_id>', methods=['DELETE'])
def delete_rack(rack_id):
    conn = get_db()
    conn.execute('DELETE FROM components WHERE parent_type = "rack" AND parent_id = ?', (rack_id,))
    conn.execute('DELETE FROM shelves WHERE rack_id = ?', (rack_id,))
    conn.execute('DELETE FROM reservoirs WHERE rack_id = ?', (rack_id,))
    conn.execute('DELETE FROM racks WHERE id = ?', (rack_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>', methods=['PUT'])
def update_rack(rack_id):
    data = request.get_json()
    name = data.get('name')
    conn = get_db()
    conn.execute('UPDATE racks SET name = ? WHERE id = ?', (name, rack_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>/structure', methods=['GET'])
def get_rack_structure(rack_id):
    conn = get_db()
    shelves = conn.execute('SELECT * FROM shelves WHERE rack_id = ? ORDER BY position', (rack_id,)).fetchall()
    reservoirs = conn.execute('SELECT * FROM reservoirs WHERE rack_id = ? ORDER BY position', (rack_id,)).fetchall()
    result = {
        'rack': dict(conn.execute('SELECT * FROM racks WHERE id = ?', (rack_id,)).fetchone()),
        'shelves': [dict(s) for s in shelves],
        'reservoirs': [dict(r) for r in reservoirs],
        'components': []
    }
    shelf_ids = [s['id'] for s in shelves]
    reservoir_ids = [r['id'] for r in reservoirs]
    all_ids = shelf_ids + reservoir_ids
    if all_ids:
        placeholders = ','.join('?' * len(all_ids))
        query = f'''
            SELECT c.*, d.name as device_name, d.ip_address, d.child_id, d.is_on
            FROM components c
            LEFT JOIN devices d ON c.device_id = d.id
            WHERE c.parent_type = 'shelf' AND c.parent_id IN ({placeholders})
        '''
        component_rows = conn.execute(query, tuple(all_ids)).fetchall()
        for comp in component_rows:
            result['components'].append(dict(comp))
    conn.close()
    return jsonify(result)

@app.route('/api/racks/<int:rack_id>/shelves', methods=['POST'])
def add_shelf(rack_id):
    data = request.get_json()
    name = data.get('name', 'New Shelf')
    position = data.get('position', 0)
    conn = get_db()
    conn.execute('INSERT INTO shelves (rack_id, name, position) VALUES (?, ?, ?)', (rack_id, name, position))
    conn.commit()
    shelf_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': shelf_id, 'rack_id': rack_id, 'name': name, 'position': position})

@app.route('/api/racks/<int:rack_id>/shelves/<int:shelf_id>', methods=['DELETE'])
def delete_shelf(rack_id, shelf_id):
    conn = get_db()
    conn.execute('DELETE FROM components WHERE parent_type = "shelf" AND parent_id = ?', (shelf_id,))
    conn.execute('DELETE FROM shelves WHERE id = ? AND rack_id = ?', (shelf_id, rack_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>/shelves/<int:shelf_id>', methods=['PUT'])
def update_shelf(rack_id, shelf_id):
    data = request.get_json()
    name = data.get('name')
    position = data.get('position')
    conn = get_db()
    if name is not None:
        conn.execute('UPDATE shelves SET name = ? WHERE id = ? AND rack_id = ?', (name, shelf_id, rack_id))
    if position is not None:
        conn.execute('UPDATE shelves SET position = ? WHERE id = ? AND rack_id = ?', (position, shelf_id, rack_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>/reservoirs', methods=['POST'])
def add_reservoir(rack_id):
    data = request.get_json()
    name = data.get('name', 'New Reservoir')
    position = data.get('position', 0)
    conn = get_db()
    conn.execute('INSERT INTO reservoirs (rack_id, name, position) VALUES (?, ?, ?)', (rack_id, name, position))
    conn.commit()
    reservoir_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': reservoir_id, 'rack_id': rack_id, 'name': name, 'position': position})

@app.route('/api/racks/<int:rack_id>/reservoirs/<int:reservoir_id>', methods=['DELETE'])
def delete_reservoir(rack_id, reservoir_id):
    conn = get_db()
    conn.execute('DELETE FROM components WHERE parent_type = "reservoir" AND parent_id = ?', (reservoir_id,))
    conn.execute('DELETE FROM reservoirs WHERE id = ? AND rack_id = ?', (reservoir_id, rack_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>/reservoirs/<int:reservoir_id>', methods=['PUT'])
def update_reservoir(rack_id, reservoir_id):
    data = request.get_json()
    name = data.get('name')
    position = data.get('position')
    conn = get_db()
    if name is not None:
        conn.execute('UPDATE reservoirs SET name = ? WHERE id = ? AND rack_id = ?', (name, reservoir_id, rack_id))
    if position is not None:
        conn.execute('UPDATE reservoirs SET position = ? WHERE id = ? AND rack_id = ?', (position, reservoir_id, rack_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

COMPONENT_TYPES = ['pump', 'light', 'aerator', 'sensor']

@app.route('/api/components', methods=['GET'])
def get_components():
    parent_type = request.args.get('parent_type')
    parent_id = request.args.get('parent_id', type=int)
    device_id = request.args.get('device_id', type=int)
    conn = get_db()
    query = 'SELECT c.*, d.name as device_name, d.ip_address, d.child_id FROM components c LEFT JOIN devices d ON c.device_id = d.id WHERE 1=1'
    params = []
    if parent_type:
        query += ' AND c.parent_type = ?'
        params.append(parent_type)
    if parent_id:
        query += ' AND c.parent_id = ?'
        params.append(parent_id)
    if device_id:
        query += ' AND c.device_id = ?'
        params.append(device_id)
    components = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(c) for c in components])

@app.route('/api/components', methods=['POST'])
def create_component():
    data = request.get_json()
    parent_type = data.get('parent_type')
    parent_id = data.get('parent_id')
    device_id = data.get('device_id')
    component_type = data.get('component_type')
    name = data.get('name')
    if not all([parent_type, parent_id, component_type, name]):
        return jsonify({'error': 'parent_type, parent_id, component_type, and name required'}), 400
    if component_type not in COMPONENT_TYPES:
        return jsonify({'error': f'component_type must be one of: {COMPONENT_TYPES}'}), 400
    conn = get_db()
    conn.execute(
        'INSERT INTO components (parent_type, parent_id, device_id, component_type, name) VALUES (?, ?, ?, ?, ?)',
        (parent_type, parent_id, device_id, component_type, name)
    )
    conn.commit()
    component_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': component_id, 'parent_type': parent_type, 'parent_id': parent_id, 'device_id': device_id, 'component_type': component_type, 'name': name})

@app.route('/api/components/<int:component_id>', methods=['DELETE'])
def delete_component(component_id):
    conn = get_db()
    conn.execute('DELETE FROM components WHERE id = ?', (component_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/components/<int:component_id>', methods=['PUT'])
def update_component(component_id):
    data = request.get_json()
    name = data.get('name')
    device_id = data.get('device_id')
    conn = get_db()
    if name is not None:
        conn.execute('UPDATE components SET name = ? WHERE id = ?', (name, component_id))
    if device_id is not None:
        conn.execute('UPDATE components SET device_id = ? WHERE id = ?', (device_id, component_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    parent_type = request.args.get('parent_type')
    parent_id = request.args.get('parent_id', type=int)
    conn = get_db()
    sensors = conn.execute('''
        SELECT c.*, d.name as device_name, d.ip_address
        FROM components c
        JOIN devices d ON c.device_id = d.id
        WHERE c.component_type = 'sensor'
    ''', (parent_type, parent_id) if parent_type and parent_id else []).fetchall()
    conn.close()
    return jsonify([dict(s) for s in sensors])

@app.route('/api/sensors/<int:sensor_id>/read', methods=['GET'])
def read_sensor(sensor_id):
    return jsonify({'sensor_id': sensor_id, 'value': None, 'error': 'Sensor integration not yet implemented'})

@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    conn = get_db()
    schedules = conn.execute('''
        SELECT s.*, d.name as device_name, d.ip_address
        FROM schedules s
        JOIN devices d ON s.device_id = d.id
        ORDER BY s.hour, s.minute
    ''').fetchall()
    conn.close()
    return jsonify([dict(s) for s in schedules])

@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    data = request.get_json()
    device_id = data.get('device_id')
    name = data.get('name')
    action = data.get('action', 'on')
    hour = data.get('hour')
    minute = data.get('minute')
    days = data.get('days', '0,1,2,3,4,5,6')

    if not all([device_id, name, hour is not None, minute is not None]):
        return jsonify({'error': 'Missing required fields'}), 400

    conn = get_db()
    conn.execute('''
        INSERT INTO schedules (device_id, name, action, hour, minute, days)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (device_id, name, action, hour, minute, days))
    conn.commit()
    schedule_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': schedule_id}), 201

@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id):
    conn = get_db()
    conn.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
def update_schedule(schedule_id):
    data = request.get_json()
    updates = []
    values = []

    for field in ['name', 'action', 'hour', 'minute', 'days', 'enabled']:
        if field in data:
            updates.append(f'{field} = ?')
            values.append(data[field])

    if not updates:
        return jsonify({'error': 'No fields to update'}), 400

    values.append(schedule_id)
    conn = get_db()
    conn.execute(f'UPDATE schedules SET {", ".join(updates)} WHERE id = ?', values)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

def check_schedules():
    now = datetime.now()
    current_day = now.weekday()
    current_hour = now.hour
    current_minute = now.minute

    conn = get_db()
    schedules = conn.execute('''
        SELECT s.*, d.account_id, d.child_id, d.ip_address
        FROM schedules s
        JOIN devices d ON s.device_id = d.id
        WHERE s.enabled = 1
    ''').fetchall()

    for schedule in schedules:
        days = [int(d) for d in schedule['days'].split(',')]
        if current_day not in days:
            continue
        if schedule['hour'] == current_hour and schedule['minute'] == current_minute:
            action = schedule['action']
            device_id = schedule['device_id']
            account_id = schedule['account_id']
            child_id = schedule['child_id']
            ip_address = schedule['ip_address']

            credentials = get_account_credentials(account_id) if account_id else None

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                desired_state = action == 'on'
                current_state = loop.run_until_complete(_get_device_state(credentials, ip_address, child_id))

                if current_state != desired_state:
                    loop.run_until_complete(_toggle_device_state(credentials, ip_address, child_id, desired_state))
                    logging.info(f"Schedule {schedule['id']}: Turned device {device_id} {action}")
                loop.close()
            except Exception as e:
                logging.error(f"Schedule {schedule['id']} error: {e}")

    conn.close()

def run_scheduler():
    scheduler.add_job(func=check_schedules, trigger='cron', second=0)
    scheduler.start()
    logging.info("Background scheduler started")

if __name__ == '__main__':
    os.makedirs('/data', exist_ok=True)
    init_db()
    run_scheduler()
    app.run(host='0.0.0.0', port=9731, debug=False)
else:
    os.makedirs('/data', exist_ok=True)
    init_db()
    run_scheduler()