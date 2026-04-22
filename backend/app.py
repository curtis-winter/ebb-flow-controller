"""
FlowBoard - EBB Flow Controller
Main Flask application for managing Kasa smart devices and grow systems.
"""
import os
import logging
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from cryptography.fernet import Fernet

from backend.database import db, Database, init_schema, get_db
from backend.constants import EDMONTON_TZ, PROVIDERS
from backend.services.schedule_service import start_scheduler

app = Flask(__name__, static_folder='../frontend', template_folder='../frontend')
CORS(app)

logging.basicConfig(
    filename='/data/app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)


def get_encryption_key():
    if os.path.exists('/data/encryption.key'):
        with open('/data/encryption.key', 'rb') as f:
            return f.read()
    key = Fernet.generate_key()
    with open('/data/encryption.key', 'wb') as f:
        f.write(key)
    return key

def encrypt_value(value):
    if not value:
        return None
    f = Fernet(get_encryption_key())
    return f.encrypt(value.encode()).decode()

def decrypt_value(encrypted_value):
    if not encrypted_value:
        return None
    f = Fernet(get_encryption_key())
    return f.decrypt(encrypted_value.encode()).decode()


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/providers', methods=['GET'])
def get_providers():
    return jsonify(PROVIDERS)


@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    with db() as database:
        accounts = database.fetch_all('SELECT id, name, provider, created_at FROM accounts ORDER BY name')
    return jsonify([Database.dict(a) for a in accounts])

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
    with db() as database:
        database.execute('DELETE FROM devices WHERE account_id = ?', (account_id,))
        database.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
        database.commit()
    return jsonify({'success': True})


@app.route('/api/logs', methods=['GET'])
def get_logs():
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


def initialize_app():
    os.makedirs('/data', exist_ok=True)
    init_schema()

    from backend.routes import devices, schedules, racks, sensors
    devices.register_routes(app)
    schedules.register_routes(app)
    racks.register_routes(app)
    sensors.register_routes(app)

    start_scheduler()

initialize_app()