# Smart Outlet Controller - Specification

## Project Overview
- **Project Name**: EBB Flow Controller (FlowBoard)
- **Type**: Web Application (Docker deployed)
- **Core Functionality**: Manage multiple Kasa brand WiFi smart outlets through a web interface
- **Target Users**: Home users managing smart home devices

## Architecture

### Technology Stack
- **Backend**: Python Flask + python-kasa + APScheduler
- **Frontend**: Single-page HTML/JS with vanilla JS
- **Database**: SQLite (for device persistence)
- **Deployment**: Docker Compose (network_mode: host)

### Components
1. **Backend API** (Flask): REST API to discover and control Kasa devices
2. **Frontend**: Web dashboard to view and control outlets
3. **Database**: Stores device configurations, schedules, and activity logs
4. **Scheduler**: Background APScheduler for automated device control

### File Structure
```
backend/
├── app.py                    # Flask routes and main application
├── constants.py              # Application constants (timezone, retries)
├── database.py               # Database utilities, schema, migrations
└── services/
    ├── __init__.py
    ├── device_service.py     # Kasa device control logic with retry
    ├── schedule_service.py   # APScheduler integration
    ├── activity_log_service.py  # Activity logging
    └── retry.py              # Retry decorator utilities
```

## Functionality Specification

### Core Features

#### Device Discovery
- Scan network for Kasa smart outlets using UDP broadcast (port 9999)
- Add devices manually by IP address
- Store discovered devices in database
- HS300 power strips shown as separate child devices

#### Device Control
- Toggle outlet on/off
- View current on/off state
- View device info (name, IP, model, MAC)
- Sequential refresh with real-time progress

#### Scheduler (v2)
New design supporting rack/shelf/device levels:
- **Target Types**: `rack`, `shelf`, `device`
- **Schedule Types**:
  - `on` - Turn on at specific time
  - `off` - Turn off at specific time  
  - `on_then_off` - Turn on, then off after duration (H:M:S)
  - `cycle` - Cycle on/off continuously

#### Activity Logging
All device operations logged with:
- Timestamp
- Device name
- Action type (toggle, refresh)
- Rack/Shelf (captured at log time)
- Device response (ON/OFF/N/A)
- Status (success/failed/error)
- Trigger source (Manual/Scheduled)
- Details (retry count)

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/devices` | List all registered devices |
| POST | `/api/devices/discover` | Discover Kasa devices on network |
| POST | `/api/devices` | Add device by IP |
| DELETE | `/api/devices/<id>` | Remove device |
| POST | `/api/devices/<id>/toggle` | Toggle device on/off |
| GET | `/api/devices/<id>/state` | Get current device state |
| PUT | `/api/devices/<id>` | Update device name |
| GET | `/api/devices/refresh` | Trigger device refresh |
| GET | `/api/devices/refresh/status` | Get refresh progress |
| GET | `/api/schedules` | List all schedules |
| POST | `/api/schedules` | Create new schedule |
| PUT | `/api/schedules/<id>` | Update schedule |
| DELETE | `/api/schedules/<id>` | Delete schedule |
| GET | `/api/logs` | Get activity logs |

### Data Models

#### Device
```
- id: INTEGER PRIMARY KEY
- account_id: INTEGER (foreign key)
- name: VARCHAR
- ip_address: VARCHAR
- mac_address: VARCHAR
- model: VARCHAR
- child_id: VARCHAR (for HS300 children)
- is_on: INTEGER (0/1)
- last_updated: TIMESTAMP
- created_at: TIMESTAMP
```

#### Schedule
```
- id: INTEGER PRIMARY KEY
- name: VARCHAR
- target_type: VARCHAR (rack/shelf/device)
- target_id: INTEGER
- schedule_type: VARCHAR (on/off/on_then_off/cycle)
- start_hour: INTEGER
- start_minute: INTEGER
- duration_seconds: INTEGER
- off_duration_seconds: INTEGER
- days: VARCHAR (comma-separated)
- enabled: INTEGER (0/1)
- created_at: TIMESTAMP
```

#### Activity Log
```
- id: INTEGER PRIMARY KEY
- device_id: INTEGER
- device_name: VARCHAR
- action_type: VARCHAR
- details: TEXT
- rack_name: TEXT
- shelf_name: TEXT
- device_response: TEXT
- device_status: TEXT
- trigger_source: TEXT
- timestamp: TIMESTAMP
```

## Configuration

### Timezone
Set via `TZ` environment variable in docker-compose.yml:
- Default: `America/Edmonton`

### Retry Configuration
In `backend/constants.py`:
```python
MAX_RETRIES = 4
RETRY_DELAYS = [1.0, 2.0, 5.0]  # seconds
```

## UI/UX Specification

### Layout Structure
- Single page dashboard with tabs
- Header with app title and action buttons
- Tab-based navigation:
  - Smart Devices (device management)
  - Grow Layout Configuration (rack/shelf builder)
  - Grow Schedule Configuration (schedules)
  - Log History (activity logs)

### Visual Design

#### Color Palette
- Background: `#0f172a` (slate-900)
- Card Background: `#1e293b` (slate-800)
- Card Border: `#334155` (slate-700)
- Primary Accent: `#22c55e` (green-500) - ON state
- Secondary Accent: `#ef4444` (red-500) - OFF state
- Text Primary: `#f8fafc` (slate-50)
- Text Secondary: `#94a3b8` (slate-400)
- Button Primary: `#3b82f6` (blue-500)
- Button Hover: `#2563eb` (blue-600)

#### Typography
- Font Family: "Outfit", sans-serif (Google Fonts)
- Headings: 600 weight
- Body: 400 weight

### Components

#### Device Card
- Device name
- Current state indicator (timestamp or refresh icon)
- IP address display
- Toggle button (Turn On/Turn Off)
- Delete button

#### Schedule Card
- Schedule name
- Target (rack/shelf/device)
- Schedule type
- Time
- Days
- Enable/disable toggle
- Delete button

#### Activity Log Table
- Frozen header
- Zebra striping
- Filtering (text search + column filter)
- Sorting (click column headers)

## Key Implementation Notes

1. **Port 9999 Discovery**: KLAP V2 fails with HS300 (v1.0), so port 9999 is used exclusively
2. **Toggle Latency**: ~3-4 seconds is normal network latency
3. **Credentials**: Stored encrypted in database using Fernet (AES-128)
4. **Timezone**: All timestamps in configurable timezone (default: America/Edmonton)
5. **Network Mode**: Uses `host` mode for UDP broadcast discovery
6. **Retry Logic**: 4 retries with 1s, 2s, 5s delays for device communication