"""
Device routes for FlowBoard.
"""
import logging
import asyncio
from datetime import datetime
from flask import jsonify, request
from kasa import Discover
from backend.database import db, Database
from backend.constants import LOCAL_TZ
from backend.services.device_service import get_device_state, toggle_device_state
from backend.services.activity_log_service import log_toggle, log_refresh
from backend.services.helpers import get_account_credentials, get_device_rack_shelf


refresh_status = {
    'in_progress': False,
    'current': None,
    'total': 0,
    'completed': 0,
    'results': []
}


def run_async(func):
    """Decorator to run async functions in Flask routes."""
    from functools import wraps
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
    import threading
    from functools import wraps
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


def register_routes(app):
    """Register device routes with Flask app."""

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
        
        disc = Discover()
        
        try:
            found_devices = await disc.discover(timeout=10)
        except Exception as e:
            logging.error(f"Discovery error: {e}")
            found_devices = {}

        results = {}
        for ip, plug in found_devices.items():
            try:
                await plug.update()
                results[ip] = {
                    'ip': ip,
                    'model': plug.model,
                    'alias': plug.alias,
                    'mac': plug.mac
                }
                logging.info(f"Discovered {plug.alias} at {ip}")
            except Exception as e:
                logging.error(f"Error updating device at {ip}: {e}")

        return jsonify(results)

    @app.route('/api/devices', methods=['POST'])
    @run_async
    async def add_device():
        """Add a new device."""
        data = request.get_json()
        ip = data.get('ip_address')
        account_id = data.get('account_id')

        logging.info(f"Adding device: IP={ip}, account_id={account_id}")
        
        if not ip:
            return jsonify({'error': 'IP address required'}), 400

        plug = None
        try:
            logging.info(f"Attempting discovery for {ip} without credentials...")
            plug = await Discover.discover_single(ip, port=9999, timeout=5)
            await plug.update()
            logging.info(f"Discovery successful for {ip}: {plug.alias}, model: {plug.model}")
        except Exception as e:
            logging.error(f"Discovery failed for {ip}: {e}")
            return jsonify({'error': f'Unable to discover device at {ip}. Error: {str(e)[:50]}'}), 500

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
                    pass

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
        
        rack_name, shelf_name = get_device_rack_shelf(device_id)
        
        state, retries = await toggle_device_state(credentials, parent_ip, child_id)
        logging.info(f"Device {device_id} toggled to {'ON' if state else 'OFF'} (retries: {retries})")

        if state is not None:
            timestamp = datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
            
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
                
                timestamp = datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
                
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