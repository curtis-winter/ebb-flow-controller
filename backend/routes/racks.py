"""
Rack routes for FlowBoard.
"""
from flask import jsonify, request
import logging
from backend.database import db, Database

logger = logging.getLogger(__name__)


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


def register_routes(app):
    """Register rack routes with Flask app."""

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
            
            shelf_ids = [s['id'] for s in shelves]
            reservoir_ids = [r['id'] for r in reservoirs]
            all_ids = shelf_ids + reservoir_ids
            
            sensors_for_shelves = {}
            sensors_for_reservoirs = {}
            if shelf_ids:
                placeholders = ','.join('?' * len(shelf_ids))
                sensor_rows = database.fetch_all(f'''
                    SELECT s.*, e.name as esp32_name
                    FROM esp32_sensors s
                    LEFT JOIN esp32_devices e ON s.esp32_id = e.id
                    WHERE s.shelf_id IN ({placeholders})
                ''', tuple(shelf_ids))
                for s in sensor_rows:
                    sid = s['shelf_id']
                    if sid not in sensors_for_shelves:
                        sensors_for_shelves[sid] = []
                    sensors_for_shelves[sid].append(Database.dict(s))
            
            if reservoir_ids:
                placeholders = ','.join('?' * len(reservoir_ids))
                sensor_rows = database.fetch_all(f'''
                    SELECT s.*, e.name as esp32_name
                    FROM esp32_sensors s
                    LEFT JOIN esp32_devices e ON s.esp32_id = e.id
                    WHERE s.reservoir_id IN ({placeholders})
                ''', tuple(reservoir_ids))
                for s in sensor_rows:
                    sid = s['reservoir_id']
                    if sid not in sensors_for_reservoirs:
                        sensors_for_reservoirs[sid] = []
                    sensors_for_reservoirs[sid].append(Database.dict(s))
            
            shelves_with_sensors = []
            for s in shelves:
                shelf_dict = Database.dict(s)
                shelf_dict['sensors'] = sensors_for_shelves.get(s['id'], [])
                shelves_with_sensors.append(shelf_dict)
            
            reservoirs_with_sensors = []
            for r in reservoirs:
                res_dict = Database.dict(r)
                res_dict['sensors'] = sensors_for_reservoirs.get(r['id'], [])
                reservoirs_with_sensors.append(res_dict)
            
            result = {
                'rack': Database.dict(database.fetch_one('SELECT * FROM racks WHERE id = ?', (rack_id,))),
                'shelves': shelves_with_sensors,
                'reservoirs': reservoirs_with_sensors,
                'components': []
            }
            
            if all_ids:
                placeholders = ','.join('?' * len(all_ids))
                query = f'''
                    SELECT c.*, d.name as device_name, d.ip_address, d.child_id, d.is_on
                    FROM components c
                    LEFT JOIN devices d ON c.device_id = d.id
                    WHERE c.parent_type IN ('shelf', 'reservoir') AND c.parent_id IN ({placeholders})
                '''
                component_rows = database.fetch_all(query, tuple(all_ids))
                result['components'] = [Database.dict(comp) for comp in component_rows]
        
        return jsonify(result)

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
        
        from backend.constants import COMPONENT_TYPES
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
        parent_type = data.get('parent_type')
        parent_id = data.get('parent_id')
        component_type = data.get('component_type')
        
        try:
            with db() as database:
                if name is not None:
                    database.execute('UPDATE components SET name = ? WHERE id = ?', (name, component_id))
                if device_id is not None:
                    database.execute('UPDATE components SET device_id = ? WHERE id = ?', (device_id, component_id))
                if parent_type is not None and parent_id is not None:
                    database.execute('UPDATE components SET parent_type = ?, parent_id = ? WHERE id = ?', (parent_type, parent_id, component_id))
                if component_type is not None:
                    database.execute('UPDATE components SET component_type = ? WHERE id = ?', (component_type, component_id))
                database.commit()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"Failed to update component {component_id}: {e}")
            return jsonify({'error': 'Failed to update component'}), 500