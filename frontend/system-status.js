// System Status Dashboard - Visual representation of grow racks
async function renderSystemStatus() {
    const diagram = document.getElementById('systemDiagram');
    if (!diagram) return;
    
    try {
        const [devices, readings, schedules, racks] = await Promise.all([
            fetch('/api/devices').then(r => r.json()),
            fetch('/api/sensors/readings?limit=100').then(r => r.json()),
            fetch('/api/schedules').then(r => r.json()),
            fetch('/api/racks').then(r => r.json())
        ]);
        
        const latestReadings = {};
        readings.forEach(r => { if (!latestReadings[r.sensor_name]) latestReadings[r.sensor_name] = r; });
        
        let html = '<div style="display: flex; flex-direction: column; gap: 24px;">';
        
        if (racks.length === 0) {
            html += '<div style="text-align: center; padding: 60px; color: #94a3b8;">';
            html += '<div style="font-size: 64px; margin-bottom: 16px;">🌱</div>';
            html += '<div style="font-size: 18px;">No grow racks configured</div>';
            html += '<div style="font-size: 14px; margin-top: 8px;">Go to System Configuration → Grow Layout to add racks</div>';
            html += '</div>';
        } else {
            for (const rack of racks) {
                const rackStructure = await fetch(`/api/racks/${rack.id}/structure`).then(r => r.json());
                html += renderRackCard(rack, rackStructure, devices, latestReadings);
            }
        }
        
        html += '</div>';
        diagram.innerHTML = html;
    } catch (e) {
        diagram.innerHTML = '<div style="color: #ef4444; text-align: center; padding: 40px;">Error: ' + e.message + '</div>';
        console.error(e);
    }
}

function renderRackCard(rack, structure, allDevices, latestReadings) {
    const shelves = structure.shelves || [];
    const components = structure.components || [];
    const reservoirs = structure.reservoirs || [];
    
    const lights = components.filter(c => c.component_type === 'light');
    const pumps = components.filter(c => c.component_type === 'pump');
    const aerators = components.filter(c => c.component_type === 'aerator');
    
    const lightsOn = lights.filter(c => c.is_on).length;
    const pumpsOn = pumps.filter(c => c.is_on).length;
    
    let html = '<div style="background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%); border-radius: 16px; padding: 20px; border: 1px solid #334155;">';
    
    // Header
    html += '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">';
    html += '<h3 style="color: #f5f5f5; margin: 0; font-size: 18px;">' + rack.name + '</h3>';
    html += '<div style="display: flex; gap: 12px;">';
    html += '<span style="background: ' + (lightsOn > 0 ? 'rgba(245,158,11,0.2)' : '#1e293b') + '; border: 1px solid ' + (lightsOn > 0 ? '#f59e0b' : '#334155') + '; border-radius: 6px; padding: 4px 12px; font-size: 12px; color: ' + (lightsOn > 0 ? '#f59e0b' : '#6b7280') + ';">💡 ' + lightsOn + '/' + lights.length + '</span>';
    html += '<span style="background: ' + (pumpsOn > 0 ? 'rgba(59,130,246,0.2)' : '#1e293b') + '; border: 1px solid ' + (pumpsOn > 0 ? '#3b82f6' : '#334155') + '; border-radius: 6px; padding: 4px 12px; font-size: 12px; color: ' + (pumpsOn > 0 ? '#3b82f6' : '#6b7280') + ';">🔄 ' + pumpsOn + '/' + pumps.length + '</span>';
    html += '</div></div>';
    
    // Visual rack with shelves
    html += '<div style="position: relative; min-height: ' + Math.max(280, shelves.length * 90 + 60) + 'px; background: rgba(15,23,42,0.5); border-radius: 12px; margin-bottom: 16px; display: flex; flex-direction: column; padding: 20px 20px 0 20px; gap: 0;">';
    
    // Render shelves from top to bottom (position 0 = top)
    const sortedShelves = [...shelves].sort((a, b) => b.position - a.position);
    
    for (let i = 0; i < Math.max(sortedShelves.length, 3); i++) {
        const shelf = sortedShelves[i];
        
        if (shelf) {
            const shelfComponents = components.filter(c => c.parent_type === 'shelf' && c.parent_id === shelf.id);
            const shelfSensors = shelf.sensors || [];
            
            const shelfLights = shelfComponents.filter(c => c.component_type === 'light');
            const shelfPumps = shelfComponents.filter(c => c.component_type === 'pump');
            
            html += '<div style="background: #1e293b; border-radius: 8px; padding: 12px; margin-bottom: ' + (i < sortedShelves.length - 1 ? '16px' : '0') + '; border: 1px solid #334155;">';
            html += '<div style="font-size: 11px; color: #94a3b8; margin-bottom: 8px;">' + shelf.name + '</div>';
            
            // Components row
            html += '<div style="display: flex; gap: 8px; flex-wrap: wrap;">';
            
            // Lights
            for (const light of shelfLights) {
                const isOn = light.is_on;
                html += '<div style="background: ' + (isOn ? 'rgba(245,158,11,0.2)' : '#0f172a') + '; border: 1px solid ' + (isOn ? '#f59e0b' : '#334155') + '; border-radius: 6px; padding: 6px 10px; display: flex; align-items: center; gap: 6px;">';
                html += '<span style="font-size: 12px;">💡</span>';
                html += '<span style="font-size: 12px; color: ' + (isOn ? '#f59e0b' : '#6b7280') + ';">' + (light.device_name || 'Light') + '</span>';
                html += '</div>';
            }
            
            // Pumps
            for (const pump of shelfPumps) {
                const isOn = pump.is_on;
                html += '<div style="background: ' + (isOn ? 'rgba(59,130,246,0.2)' : '#0f172a') + '; border: 1px solid ' + (isOn ? '#3b82f6' : '#334155') + '; border-radius: 6px; padding: 6px 10px; display: flex; align-items: center; gap: 6px;">';
                html += '<span style="font-size: 12px;">🔄</span>';
                html += '<span style="font-size: 12px; color: ' + (isOn ? '#3b82f6' : '#6b7280') + ';">' + (pump.device_name || 'Pump') + '</span>';
                html += '</div>';
            }
            
            // Sensors (from shelf.sensors)
            for (const sensor of shelfSensors) {
                const reading = latestReadings[sensor.name];
                html += '<div style="background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 6px 10px; display: flex; align-items: center; gap: 6px;">';
                html += '<span style="font-size: 12px;">📊</span>';
                html += '<span style="font-size: 12px; color: #94a3b8;">' + (sensor.name || 'Sensor') + '</span>';
                if (reading && reading.value !== undefined) {
                    html += '<span style="font-size: 12px; color: #f59e0b; font-weight: 600;">' + reading.value.toFixed(1) + '</span>';
                }
                html += '</div>';
            }
            
            if (shelfLights.length === 0 && shelfPumps.length === 0 && shelfSensors.length === 0) {
                html += '<span style="color: #4b5563; font-size: 12px; font-style: italic;">Empty shelf</span>';
            }
            
            html += '</div></div>';
        } else if (i < 3) {
            // Empty shelf placeholder for layout visualization
            html += '<div style="background: rgba(30,41,59,0.5); border-radius: 8px; padding: 12px; margin-bottom: 16px; border: 1px dashed #334155; text-align: center;">';
            html += '<span style="color: #4b5563; font-size: 12px; font-style: italic;">Empty slot</span>';
            html += '</div>';
        }
    }
    
    // Reservoirs at bottom
    if (reservoirs.length > 0) {
        html += '<div style="background: #0f172a; border-radius: 8px 8px 12px 12px; padding: 16px; margin-top: auto; border: 1px solid #059669;">';
        html += '<div style="display: flex; gap: 16px; flex-wrap: wrap;">';
        
        for (const res of reservoirs) {
            html += '<div style="background: #1e293b; border: 1px solid #059669; border-radius: 6px; padding: 8px 12px; display: flex; align-items: center; gap: 8px;">';
            html += '<span style="font-size: 14px;">💧</span>';
            html += '<span style="font-size: 13px; color: #34d399;">' + res.name + '</span>';
            
            // Find pumps feeding this reservoir
            const resPumps = components.filter(c => c.parent_type === 'reservoir' && c.parent_id === res.id);
            for (const pump of resPumps) {
                const isOn = pump.is_on;
                html += '<span style="font-size: 12px; color: ' + (isOn ? '#3b82f6' : '#6b7280') + ';">' + (pump.device_name || 'Pump') + '</span>';
            }
            html += '</div>';
        }
        
        html += '</div></div>';
    }
    
    // Add shelf bottom rails
    if (shelves.length === 0) {
        html += '<div style="flex: 1;"></div>';
    }
    
    html += '</div></div>';
    
    return html;
}
