"""
Schedule routes for FlowBoard.
"""
from flask import jsonify, request
from backend.database import db, Database
from backend.constants import TARGET_TYPES, SCHEDULE_TYPES


def register_routes(app):
    """Register schedule routes with Flask app."""

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
        target_type = data.get('target_type')
        target_id = data.get('target_id')
        schedule_type = data.get('schedule_type')
        start_hour = data.get('start_hour')
        start_minute = data.get('start_minute')
        duration_seconds = data.get('duration_seconds', 0)
        off_duration_seconds = data.get('off_duration_seconds', 0)
        days = data.get('days', '0,1,2,3,4,5,6')

        if not all([name, target_type, target_id, schedule_type, start_hour is not None, start_minute is not None]):
            return jsonify({'error': 'Missing required fields'}), 400

        if target_type not in TARGET_TYPES or schedule_type not in SCHEDULE_TYPES:
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