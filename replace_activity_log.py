import re

with open('backend/app.py', 'r') as f:
    content = f.read()

new_function = """@app.route('/api/activity-log', methods=['GET'])
def get_activity_log():
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    rack_id = request.args.get('rack_id', type=int)
    device_id = request.args.get('device_id', type=int)
    
    conn = get_db()
    query = '''
SELECT al.*, d.name as device_name, rack_info.rack_name
FROM activity_log al
LEFT JOIN devices d ON al.device_id = d.id
LEFT JOIN (
    SELECT c.device_id, r.id as rack_id, r.name as rack_name
    FROM components c
    JOIN shelves s ON c.parent_id = s.id AND c.parent_type = 'shelf'
    JOIN racks r ON s.rack_id = r.id
    UNION ALL
    SELECT c.device_id, r.id as rack_id, r.name as rack_name
    FROM components c
    JOIN reservoirs res ON c.parent_id = res.id AND c.parent_type = 'reservoir'
    JOIN racks r ON res.rack_id = r.id
) rack_info ON al.device_id = rack_info.device_id
'''
    params = []
    conditions = []
    
    if rack_id:
        conditions.append('rack_info.rack_id = ?')
        params.append(rack_id)
    if device_id:
        conditions.append('al.device_id = ?')
        params.append(device_id)
    
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    
    query += ' ORDER BY al.timestamp DESC LIMIT ? OFFSET ?'
    params.extend([limit, offset])
    
    logs = conn.execute(query, params).fetchall()
    conn.close()
    
    return jsonify([dict(row) for row in logs])
"""

# Replace the function using a pattern that matches from the route decorator to the next route decorator or end of file.
# We'll use a regex that matches the function we want to replace.
pattern = r'(@app\.route\(\'/api/activity-log\', methods=\[\'GET\'\]\)\s*def get_activity_log\(\):.*?)(?=@app\.route|\Z)'
new_content = re.sub(pattern, new_function, content, flags=re.DOTALL)

with open('backend/app.py', 'w') as f:
    f.write(new_content)

print('Replaced get_activity_log function')
