import os
import json
import asyncio
import logging
from functools import wraps
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import sqlite3
from kasa import Discover, Credentials
from cryptography.fernet import Fernet

logging.basicConfig(filename='/data/app.log', level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

app = Flask(__name__, static_folder='../frontend', template_folder='../frontend')
CORS(app)

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
    existing = {row['ip_address']: row for row in conn.execute('SELECT * FROM devices').fetchall()}
    conn.close()

    new_devices = {ip: data for ip, data in result.items() if ip not in existing}
    return jsonify(new_devices)

@app.route('/api/devices', methods=['POST'])
@run_async
async def add_device():
    data = request.get_json()
    ip = data.get('ip_address')
    account_id = data.get('account_id')

    if not ip:
        return jsonify({'error': 'IP address required'}), 400

    credentials = get_account_credentials(account_id) if account_id else None

    try:
        plug = await Discover.discover_single(ip, credentials=credentials)
        await plug.update()
    except Exception as e:
        try:
            plug = await Discover.discover_single(ip, credentials=credentials, port=9999)
            await plug.update()
        except Exception as e2:
            logging.error(f"Error getting device info for {ip}: {e}, fallback also failed: {e2}")
            device_info = {'devices': [{'name': 'Unknown Device', 'mac': '', 'model': '', 'child_id': None}], 'is_parent': False}
            children = []
        children = getattr(plug, 'children', []) or []
        if children:
            devices = []
            for i, child in enumerate(children):
                await child.update()
                name = child.alias or f"Plug {i+1}"
                devices.append({
                    'name': name,
                    'mac': child.mac,
                    'model': child.model,
                    'child_id': child.device_id
                })
            device_info = {'devices': devices, 'is_parent': True}
        else:
            name = plug.alias or plug.model or 'Smart Outlet'
            device_info = {'devices': [{'name': name, 'mac': plug.mac, 'model': plug.model, 'child_id': None}], 'is_parent': False}
    except Exception as e:
        logging.error(f"Error getting device info for {ip}: {e}")
        device_info = {'devices': [{'name': 'Unknown Device', 'mac': '', 'model': '', 'child_id': None}], 'is_parent': False}

    conn = get_db()
    added_ids = []
    for dev in device_info['devices']:
        try:
            conn.execute(
                'INSERT INTO devices (account_id, name, ip_address, mac_address, model, child_id) VALUES (?, ?, ?, ?, ?, ?)',
                (account_id, dev['name'], ip, dev['mac'], dev['model'], dev['child_id'])
            )
            conn.commit()
            device_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            added_ids.append({'id': device_id, 'name': dev['name'], 'ip_address': ip})
        except sqlite3.IntegrityError:
            pass
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

async def _toggle_device_state(credentials, parent_ip, child_id):
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
                    await child.turn_on() if not child.is_on else await child.turn_off()
                    await asyncio.sleep(1)
                    await plug.update()
                    for c in plug.children:
                        if c.device_id == child_id:
                            return c.is_on
                return None
            else:
                await plug.toggle()
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
    state = await _toggle_device_state(credentials, parent_ip, child_id)

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

if __name__ == '__main__':
    os.makedirs('/data', exist_ok=True)
    init_db()
    app.run(host='0.0.0.0', port=9731, debug=False)
else:
    os.makedirs('/data', exist_ok=True)
    init_db()