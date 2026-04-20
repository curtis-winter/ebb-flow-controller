"""
FlowBoard - EBB Flow Controller
Main Flask application for managing Kasa smart devices and grow systems.
"""
import os
import asyncio
import threading
import logging
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from cryptography.fernet import Fernet
from zoneinfo import ZoneInfo

from kasa import Discover, Credentials

from backend.database import db, Database, init_schema, get_db
from backend.constants import EDMONTON_TZ
from backend.services.device_service import get_device_state, toggle_device_state, discover_device
from backend.services.schedule_service import start_scheduler
from backend.services.activity_log_service import log_toggle, log_refresh

# Initialize Flask app
app = Flask(__name__, static_folder='../frontend', template_folder='../frontend')
CORS(app)

# Configure logging
logging.basicConfig(
    filename='/data/app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

PROVIDERS = ['kasa', 'tapo']

# ============================================================================
# Helper Functions
# ============================================================================

def run_async(func):
    """Decorator to run async functions in Flask routes."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(func(*args, **kwargs))
        finally:
            loop.close()
    return wrapper


def run_async_background(func):
    """Decorator to run async functions in background (non-blocking)."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        def run_in_background():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(func(*args, **kwargs))
            finally:
                loop.close()
        thread = threading.Thread(target=run_in_background, daemon=True)
        thread.start()
        return jsonify({'success': True, 'message': 'Refresh started in background'})
    return wrapper

def get_encryption_key():
    """Get or create the encryption key."""
    if os.path.exists('/data/encryption.key'):
        with open('/data/encryption.key', 'rb') as f:
            return f.read()
    key = Fernet.generate_key()
    with open('/data/encryption.key', 'wb') as f:
        f.write(key)
    return key

def encrypt_value(value):
    """Encrypt a value using Fernet encryption."""
    if not value:
        return None
    f = Fernet(get_encryption_key())
    return f.encrypt(value.encode()).decode()

def decrypt_value(encrypted_value):
    """Decrypt a value using Fernet encryption."""
    if not encrypted_value:
        return None
    f = Fernet(get_encryption_key())
    return f.decrypt(encrypted_value.encode()).decode()

def get_account_credentials(account_id):
    """Get Kasa credentials for an account."""
    with db() as database:
        account = database.fetch_one('SELECT * FROM accounts WHERE id = ?', (account_id,))
    
    if not account:
        return None
    
    if account['provider'] in ('kasa', 'tapo'):
        username = decrypt_value(account['username_encrypted'])
        password = decrypt_value(account['password_encrypted'])
        if username and password:
            return Credentials(username=username, password=password)
    return None

# ============================================================================
# Flask Routes - Core
# ============================================================================

@app.route('/')
def index():
    """Serve the main application page."""
    return render_template('index.html')

@app.route('/api/providers', methods=['GET'])
def get_providers():
    """Get list of supported providers."""
    return jsonify(PROVIDERS)

# ============================================================================
# Flask Routes - Accounts
# ============================================================================

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """Get all accounts."""
    with db() as database:
        accounts = database.fetch_all('SELECT id, name, provider, created_at FROM accounts ORDER BY name')
    return jsonify([Database.dict(a) for a in accounts])

@app.route('/api/accounts', methods=['POST'])
def create_account():
    """Create a new account."""
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

    with db() as database:
        database.execute(
            'INSERT INTO accounts (name, provider, username_encrypted, password_encrypted) VALUES (?, ?, ?, ?)',
            (name, provider, username_enc, password_enc)
        )
        database.commit()
        account_id = database.fetch_one('SELECT last_insert_rowid()')[0]

    return jsonify({'id': account_id, 'name': name, 'provider': provider})

@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
def delete_account(account_id):
    """Delete an account and all associated devices."""
    with db() as database:
        database.execute('DELETE FROM devices WHERE account_id = ?', (account_id,))
        database.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
        database.commit()
    return jsonify({'success': True})

# ============================================================================
# Flask Routes - Devices
# ============================================================================

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get all devices, optionally filtered by account."""
    account_id = request.args.get('account_id', type=int)
    with db() as database:
        if account_id:
            devices = database.fetch_all(
                'SELECT * FROM devices WHERE account_id = ? ORDER BY created_at DESC',
                (account_id,)
            )
        else:
            devices = database.fetch_all('SELECT * FROM devices ORDER BY created_at DESC')
    return jsonify([Database.dict(d) for d in devices])

@app.route('/api/devices/discover', methods=['POST'])
@run_async
async def discover_devices():
    """Discover devices on the network."""
    account_id = request.json.get('account_id') if request.is_json else None
    credentials = get_account_credentials(account_id) if account_id else None
    
    disc = Discover()
    found_devices = await disc.discover()
    
    results = []
    for ip, plug in found_devices.items():
        try:
            await plug.update()
            results.append({
                'ip': ip,
                'model': plug.model,
                'alias': plug.alias,
                'mac': plug.mac
            })
        except Exception as e:
            logging.error(f"Error discovering device at {ip}: {e}")
    
    return jsonify(results)

@app.route('/api/devices', methods=['POST'])
@run_async
async def add_device():
    """Add a new device."""
    data = request.get_json()
    ip = data.get('ip_address')
    account_id = data.get('account_id')

    if not ip:
        return jsonify({'error': 'IP address required'}), 400

    credentials = get_account_credentials(account_id) if account_id else None

    # Discover device
    plug = await discover_device(ip, credentials)
    if not plug:
        return jsonify({'error': 'Unable to discover device'}), 500

    # Build device payload
    parent_dev = {
        'name': plug.alias or 'Smart Outlet',
        'mac_address': plug.mac,
        'model': plug.model,
        'child_id': None,
    }

    children = getattr(plug, 'children', [])
    child_devs = [
        {
            'name': child.alias or f'Child {child.device_id}',
            'mac_address': child.mac,
            'model': child.model,
            'child_id': child.device_id,
        }
        for child in children
    ]

    device_payload = [parent_dev] + child_devs

    # Insert devices
    added_ids = []
    with db() as database:
        for dev in device_payload:
            try:
                database.execute(
                    'INSERT INTO devices (account_id, name, ip_address, mac_address, model, child_id) VALUES (?,?,?,?,?,?)',
                    (account_id, dev['name'], ip, dev['mac_address'], dev['model'], dev.get('child_id'))
                )
                database.commit()
                new_id = database.fetch_one('SELECT last_insert_rowid()')[0]
                added_ids.append({'id': new_id, 'name': dev['name'], 'ip_address': ip})
            except Exception:
                pass  # Device may already exist

    if not added_ids:
        return jsonify({'error': 'Device already exists'}), 400

    return jsonify(added_ids)

@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
def delete_device(device_id):
    """Delete a device."""
    with db() as database:
        database.execute('DELETE FROM devices WHERE id = ?', (device_id,))
        database.commit()
    return jsonify({'success': True})

@app.route('/api/devices/<int:device_id>', methods=['PUT'])
def update_device(device_id):
    """Update device name."""
    data = request.get_json()
    name = data.get('name')

    with db() as database:
        database.execute('UPDATE devices SET name = ? WHERE id = ?', (name, device_id))
        database.commit()
    return jsonify({'success': True})

@app.route('/api/devices/<int:device_id>/toggle', methods=['POST'])
@run_async
async def toggle_device(device_id):
    """Toggle device state."""
    with db() as database:
        device = database.fetch_one('SELECT * FROM devices WHERE id = ?', (device_id,))

        if not device:
            return jsonify({'error': 'Device not found'}), 404

        account_id = device['account_id']
        child_id = device['child_id']
        parent_ip = device['ip_address']
        device_name = device['name']
        initial_state = device['is_on']

    credentials = get_account_credentials(account_id) if account_id else None
    logging.info(f"Toggling device {device_id} ({device_name})")
    
    # Get rack/shelf at log time
    rack_name, shelf_name = get_device_rack_shelf(device_id)
    
    state, retries = await toggle_device_state(credentials, parent_ip, child_id)
    logging.info(f"Device {device_id} toggled to {'ON' if state else 'OFF'} (retries: {retries})")

    if state is not None:
        timestamp = datetime.now(EDMONTON_TZ).strftime('%Y-%m-%d %H:%M:%S')
        
        with db() as database:
            database.execute(
                'UPDATE devices SET is_on = ?, last_updated = ? WHERE id = ?',
                (1 if state else 0, timestamp, device_id)
            )
            database.commit()
        
        log_toggle(
            device_id=device_id,
            device_name=device_name,
            device_response='ON' if state else 'OFF',
            device_status='success',
            trigger_source='Manual',
            rack_name=rack_name,
            shelf_name=shelf_name,
            retries=retries,
        )

    if state is None:
        log_toggle(
            device_id=device_id,
            device_name=device_name,
            device_response=None,
            device_status='failed',
            trigger_source='Manual',
            rack_name=rack_name,
            shelf_name=shelf_name,
            retries=0,
        )
        return jsonify({'error': 'Failed to toggle device'}), 500

    return jsonify({'is_on': state})

@app.route('/api/devices/<int:device_id>/state', methods=['GET'])
@run_async
async def get_device_state_route(device_id):
    """Get current device state."""
    with db() as database:
        device = database.fetch_one('SELECT * FROM devices WHERE id = ?', (device_id,))

        if not device:
            return jsonify({'error': 'Device not found'}), 404

        account_id = device['account_id']
        child_id = device['child_id']
        parent_ip = device['ip_address']

    credentials = get_account_credentials(account_id) if account_id else None
    state, retries = await get_device_state(credentials, parent_ip, child_id)

    if state is None:
        return jsonify({'is_on': None, 'error': 'Device unreachable'})

    return jsonify({'is_on': state, 'retries': retries})

# Refresh status tracker
refresh_status = {
    'in_progress': False,
    'current': None,
    'total': 0,
    'completed': 0,
    'results': []
}

@app.route('/api/devices/refresh', methods=['POST'])
@run_async_background
async def refresh_devices():
    """Refresh all device states sequentially with progress tracking."""
    global refresh_status
    
    if refresh_status['in_progress']:
        return jsonify({'error': 'Refresh already in progress'}), 409
    
    with db() as database:
        devices = database.fetch_all('SELECT * FROM devices')
        device_list = [dict(d) for d in devices if d['account_id'] and d['ip_address']]
    
    refresh_status['in_progress'] = True
    refresh_status['current'] = None
    refresh_status['total'] = len(device_list)
    refresh_status['completed'] = 0
    refresh_status['results'] = []
    
    try:
        for idx, device in enumerate(device_list):
            if idx > 0:
                await asyncio.sleep(2.0)
            
            refresh_status['current'] = device['id']
            
            timestamp = datetime.now(EDMONTON_TZ).strftime('%Y-%m-%d %H:%M:%S')
            
            # Get rack/shelf at log time
            rack_name, shelf_name = get_device_rack_shelf(device['id'])
            
            try:
                creds = get_account_credentials(device['account_id'])
                state, retries = await get_device_state(creds, device['ip_address'], device['child_id'])
                
                with db() as database:
                    if state is not None:
                        database.execute('UPDATE devices SET is_on = ?, last_updated = ? WHERE id = ?', (1 if state else 0, timestamp, device['id']))
                        database.commit()
                
                log_refresh(
                    device_id=device['id'],
                    device_name=device['name'],
                    device_response='ON' if state else ('OFF' if state is not None else None),
                    device_status='success' if state is not None else 'failed',
                    rack_name=rack_name,
                    shelf_name=shelf_name,
                    retries=retries,
                )
                
                result = {
                    'id': device['id'],
                    'name': device['name'],
                    'state': state,
                    'retries': retries,
                    'success': state is not None,
                    'timestamp': timestamp
                }
                refresh_status['results'].append(result)
                refresh_status['completed'] = idx + 1
                
                logging.info(f"Refreshed device {device['id']}: {device['name']} = {'ON' if state else 'OFF'} (retries: {retries})")
                    
            except Exception as e:
                logging.error(f"Refresh error for device {device['id']}: {e}")
                log_refresh(
                    device_id=device['id'],
                    device_name=device['name'],
                    device_response=None,
                    device_status='error',
                    rack_name=rack_name,
                    shelf_name=shelf_name,
                    error=f"error:{str(e)}",
                )
                refresh_status['results'].append({
                    'id': device['id'],
                    'name': device['name'],
                    'state': None,
                    'success': False,
                    'error': str(e)
                })
                refresh_status['completed'] = idx + 1
    
    finally:
        refresh_status['in_progress'] = False
        refresh_status['current'] = None
    
    return jsonify({'success': True, 'total': refresh_status['total'], 'completed': refresh_status['completed']})

@app.route('/api/devices/refresh/status', methods=['GET'])
def get_refresh_status():
    """Get current refresh progress."""
    return jsonify(refresh_status)

# ============================================================================
# Flask Routes - Logs
# ============================================================================

def get_device_rack_shelf(device_id):
    """Get the current rack and shelf name for a device."""
    with db() as database:
        result = database.fetch_one('''
            SELECT r.name as rack_name, s.name as shelf_name
            FROM components c
            JOIN shelves s ON s.id = c.parent_id AND c.parent_type = 'shelf'
            JOIN racks r ON r.id = s.rack_id
            WHERE c.device_id = ?
            LIMIT 1
        ''', (device_id,))
        if result:
            return (result['rack_name'], result['shelf_name'])
        return (None, None)

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get activity logs."""
    with db() as database:
        logs = database.fetch_all('SELECT * FROM activity_log ORDER BY id DESC LIMIT 100')
    
    result = []
    for log in logs:
        log_dict = Database.dict(log)
        ts = log_dict.get('timestamp')
        if ts:
            log_dict['timestamp'] = f"{ts} MDT"
        result.append(log_dict)
    
    return jsonify(result)

# ============================================================================
# Flask Routes - Racks (CRUD helpers)
# ============================================================================

def _get_racks():
    """Helper to get all racks."""
    with db() as database:
        return database.fetch_all('SELECT * FROM racks ORDER BY is_default DESC, name')

def _create_rack(name):
    """Helper to create a rack."""
    with db() as database:
        database.execute('INSERT INTO racks (name) VALUES (?)', (name,))
        database.commit()
        return database.fetch_one('SELECT last_insert_rowid()')[0]

def _delete_rack(rack_id):
    """Helper to delete a rack and all related data."""
    with db() as database:
        database.execute('DELETE FROM components WHERE parent_type = "rack" AND parent_id = ?', (rack_id,))
        database.execute('DELETE FROM shelves WHERE rack_id = ?', (rack_id,))
        database.execute('DELETE FROM reservoirs WHERE rack_id = ?', (rack_id,))
        database.execute('DELETE FROM racks WHERE id = ?', (rack_id,))
        database.commit()

def _update_rack(rack_id, name):
    """Helper to update a rack."""
    with db() as database:
        database.execute('UPDATE racks SET name = ? WHERE id = ?', (name, rack_id))
        database.commit()

def _set_default_rack(rack_id):
    """Helper to set default rack."""
    with db() as database:
        database.execute('UPDATE racks SET is_default = 0')
        database.execute('UPDATE racks SET is_default = 1 WHERE id = ?', (rack_id,))
        database.commit()

# ============================================================================
# Flask Routes - Racks
# ============================================================================

@app.route('/api/racks', methods=['GET'])
def get_racks():
    """Get all racks."""
    racks = _get_racks()
    return jsonify([Database.dict(r) for r in racks])

@app.route('/api/racks', methods=['POST'])
def create_rack():
    """Create a new rack."""
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({'error': 'Name required'}), 400
    
    rack_id = _create_rack(name)
    return jsonify({'id': rack_id, 'name': name})

@app.route('/api/racks/<int:rack_id>', methods=['DELETE'])
def delete_rack(rack_id):
    """Delete a rack."""
    _delete_rack(rack_id)
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>', methods=['PUT'])
def update_rack(rack_id):
    """Update a rack."""
    data = request.get_json()
    name = data.get('name')
    _update_rack(rack_id, name)
    return jsonify({'success': True})

@app.route('/api/racks/default/<int:rack_id>', methods=['POST'])
def set_default_rack(rack_id):
    """Set default rack."""
    _set_default_rack(rack_id)
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>/structure', methods=['GET'])
def get_rack_structure(rack_id):
    """Get complete rack structure."""
    with db() as database:
        shelves = database.fetch_all('SELECT * FROM shelves WHERE rack_id = ? ORDER BY position', (rack_id,))
        reservoirs = database.fetch_all('SELECT * FROM reservoirs WHERE rack_id = ? ORDER BY position', (rack_id,))
        
        result = {
            'rack': Database.dict(database.fetch_one('SELECT * FROM racks WHERE id = ?', (rack_id,))),
            'shelves': [Database.dict(s) for s in shelves],
            'reservoirs': [Database.dict(r) for r in reservoirs],
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
            component_rows = database.fetch_all(query, tuple(all_ids))
            result['components'] = [Database.dict(comp) for comp in component_rows]
    
    return jsonify(result)

# ============================================================================
# Flask Routes - Shelves
# ============================================================================

@app.route('/api/racks/<int:rack_id>/shelves', methods=['POST'])
def add_shelf(rack_id):
    """Add a shelf to a rack."""
    data = request.get_json()
    name = data.get('name', 'New Shelf')
    position = data.get('position', 0)
    
    with db() as database:
        database.execute('INSERT INTO shelves (rack_id, name, position) VALUES (?, ?, ?)', (rack_id, name, position))
        database.commit()
        shelf_id = database.fetch_one('SELECT last_insert_rowid()')[0]
    
    return jsonify({'id': shelf_id, 'rack_id': rack_id, 'name': name, 'position': position})

@app.route('/api/racks/<int:rack_id>/shelves/<int:shelf_id>', methods=['DELETE'])
def delete_shelf(rack_id, shelf_id):
    """Delete a shelf."""
    with db() as database:
        database.execute('DELETE FROM components WHERE parent_type = "shelf" AND parent_id = ?', (shelf_id,))
        database.execute('DELETE FROM shelves WHERE id = ? AND rack_id = ?', (shelf_id, rack_id))
        database.commit()
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>/shelves/<int:shelf_id>', methods=['PUT'])
def update_shelf(rack_id, shelf_id):
    """Update a shelf."""
    data = request.get_json()
    name = data.get('name')
    position = data.get('position')
    
    with db() as database:
        if name is not None:
            database.execute('UPDATE shelves SET name = ? WHERE id = ? AND rack_id = ?', (name, shelf_id, rack_id))
        if position is not None:
            database.execute('UPDATE shelves SET position = ? WHERE id = ? AND rack_id = ?', (position, shelf_id, rack_id))
        database.commit()
    
    return jsonify({'success': True})

# ============================================================================
# Flask Routes - Reservoirs
# ============================================================================

@app.route('/api/racks/<int:rack_id>/reservoirs', methods=['POST'])
def add_reservoir(rack_id):
    """Add a reservoir to a rack."""
    data = request.get_json()
    name = data.get('name', 'New Reservoir')
    position = data.get('position', 0)
    
    with db() as database:
        database.execute('INSERT INTO reservoirs (rack_id, name, position) VALUES (?, ?, ?)', (rack_id, name, position))
        database.commit()
        reservoir_id = database.fetch_one('SELECT last_insert_rowid()')[0]
    
    return jsonify({'id': reservoir_id, 'rack_id': rack_id, 'name': name, 'position': position})

@app.route('/api/racks/<int:rack_id>/reservoirs/<int:reservoir_id>', methods=['DELETE'])
def delete_reservoir(rack_id, reservoir_id):
    """Delete a reservoir."""
    with db() as database:
        database.execute('DELETE FROM components WHERE parent_type = "reservoir" AND parent_id = ?', (reservoir_id,))
        database.execute('DELETE FROM reservoirs WHERE id = ? AND rack_id = ?', (reservoir_id, rack_id))
        database.commit()
    return jsonify({'success': True})

@app.route('/api/racks/<int:rack_id>/reservoirs/<int:reservoir_id>', methods=['PUT'])
def update_reservoir(rack_id, reservoir_id):
    """Update a reservoir."""
    data = request.get_json()
    name = data.get('name')
    position = data.get('position')
    
    with db() as database:
        if name is not None:
            database.execute('UPDATE reservoirs SET name = ? WHERE id = ? AND rack_id = ?', (name, reservoir_id, rack_id))
        if position is not None:
            database.execute('UPDATE reservoirs SET position = ? WHERE id = ? AND rack_id = ?', (position, reservoir_id, rack_id))
        database.commit()
    
    return jsonify({'success': True})

# ============================================================================
# Flask Routes - Components
# ============================================================================

COMPONENT_TYPES = ['pump', 'light', 'aerator', 'sensor']

@app.route('/api/components', methods=['GET'])
def get_components():
    """Get components with optional filters."""
    parent_type = request.args.get('parent_type')
    parent_id = request.args.get('parent_id', type=int)
    device_id = request.args.get('device_id', type=int)
    
    with db() as database:
        query = '''
            SELECT c.*, d.name as device_name, d.ip_address, d.child_id
            FROM components c
            LEFT JOIN devices d ON c.device_id = d.id
            WHERE 1=1
        '''
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
        
        components = database.fetch_all(query, params)
    
    return jsonify([Database.dict(c) for c in components])

@app.route('/api/components', methods=['POST'])
def create_component():
    """Create a new component."""
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
    
    with db() as database:
        database.execute(
            'INSERT INTO components (parent_type, parent_id, device_id, component_type, name) VALUES (?, ?, ?, ?, ?)',
            (parent_type, parent_id, device_id, component_type, name)
        )
        database.commit()
        component_id = database.fetch_one('SELECT last_insert_rowid()')[0]
    
    return jsonify({
        'id': component_id,
        'parent_type': parent_type,
        'parent_id': parent_id,
        'device_id': device_id,
        'component_type': component_type,
        'name': name
    })

@app.route('/api/components/<int:component_id>', methods=['DELETE'])
def delete_component(component_id):
    """Delete a component."""
    with db() as database:
        database.execute('DELETE FROM components WHERE id = ?', (component_id,))
        database.commit()
    return jsonify({'success': True})

@app.route('/api/components/<int:component_id>', methods=['PUT'])
def update_component(component_id):
    """Update a component."""
    data = request.get_json()
    name = data.get('name')
    device_id = data.get('device_id')
    
    with db() as database:
        if name is not None:
            database.execute('UPDATE components SET name = ? WHERE id = ?', (name, component_id))
        if device_id is not None:
            database.execute('UPDATE components SET device_id = ? WHERE id = ?', (device_id, component_id))
        database.commit()
    
    return jsonify({'success': True})

# ============================================================================
# Flask Routes - Schedules
# ============================================================================

@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    """Get all schedules with target info."""
    target_type = request.args.get('target_type')
    target_id = request.args.get('target_id', type=int)
    
    with db() as database:
        query = 'SELECT s.* FROM schedules s WHERE 1=1'
        params = []
        
        if target_type:
            query += ' AND s.target_type = ?'
            params.append(target_type)
        if target_id:
            query += ' AND s.target_id = ?'
            params.append(target_id)
        
        query += ' ORDER BY s.start_hour, s.start_minute'
        
        schedules = database.fetch_all(query, params)
    
    result = []
    for s in schedules:
        sched = Database.dict(s)
        # Add target name based on type
        if sched['target_type'] == 'rack':
            with db() as database:
                rack = database.fetch_one('SELECT name FROM racks WHERE id = ?', (sched['target_id'],))
                if rack:
                    sched['target_name'] = rack['name']
        elif sched['target_type'] == 'shelf':
            with db() as database:
                shelf = database.fetch_one('SELECT name, rack_id FROM shelves WHERE id = ?', (sched['target_id'],))
                if shelf:
                    sched['target_name'] = shelf['name']
                    rack = database.fetch_one('SELECT name FROM racks WHERE id = ?', (shelf['rack_id'],))
                    sched['rack_name'] = rack['name'] if rack else ''
        elif sched['target_type'] == 'device':
            with db() as database:
                dev = database.fetch_one('SELECT name FROM devices WHERE id = ?', (sched['target_id'],))
                if dev:
                    sched['target_name'] = dev['name']
        result.append(sched)
    
    return jsonify(result)

@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    """Create a new schedule."""
    data = request.get_json()
    name = data.get('name')
    target_type = data.get('target_type')  # 'rack', 'shelf', or 'device'
    target_id = data.get('target_id')
    schedule_type = data.get('schedule_type')  # 'on', 'off', 'on_then_off', 'cycle'
    start_hour = data.get('start_hour')
    start_minute = data.get('start_minute')
    duration_seconds = data.get('duration_seconds', 0)
    off_duration_seconds = data.get('off_duration_seconds', 0)
    days = data.get('days', '0,1,2,3,4,5,6')

    if not all([name, target_type, target_id, schedule_type, start_hour is not None, start_minute is not None]):
        return jsonify({'error': 'Missing required fields'}), 400

    valid_types = ['rack', 'shelf', 'device']
    valid_schedule_types = ['on', 'off', 'on_then_off', 'cycle']
    
    if target_type not in valid_types or schedule_type not in valid_schedule_types:
        return jsonify({'error': 'Invalid target_type or schedule_type'}), 400

    with db() as database:
        database.execute('''
            INSERT INTO schedules (name, target_type, target_id, schedule_type, start_hour, start_minute, duration_seconds, off_duration_seconds, days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, target_type, target_id, schedule_type, start_hour, start_minute, duration_seconds, off_duration_seconds, days))
        database.commit()
        schedule_id = database.fetch_one('SELECT last_insert_rowid()')[0]
    
    return jsonify({'id': schedule_id}), 201

@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id):
    """Delete a schedule."""
    with db() as database:
        database.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
        database.commit()
    return jsonify({'success': True})

@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
def update_schedule(schedule_id):
    """Update a schedule."""
    data = request.get_json()
    updates = []
    values = []

    for field in ['name', 'target_type', 'target_id', 'schedule_type', 'start_hour', 'start_minute', 'duration_seconds', 'off_duration_seconds', 'days', 'enabled']:
        if field in data and data[field] is not None:
            updates.append(f'{field} = ?')
            values.append(data[field])

    if not updates:
        return jsonify({'error': 'No fields to update'}), 400

    values.append(schedule_id)
    with db() as database:
        database.execute(f'UPDATE schedules SET {", ".join(updates)} WHERE id = ?', values)
        database.commit()
    
    return jsonify({'success': True})

# ============================================================================
# Application Initialization
# ============================================================================

def initialize_app():
    """Initialize the application database and scheduler."""
    os.makedirs('/data', exist_ok=True)
    init_schema()
    start_scheduler()

# Initialize when module is imported
initialize_app()
