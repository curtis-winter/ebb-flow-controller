# FlowBoard

## Quick Start

```bash
docker compose up --build -d # Build and start
docker logs flowboard # View logs
docker compose down # Stop
```

## Key Details

- **Port**: 9731
- **Network**: Uses `network_mode: host` for Kasa device discovery (UDP broadcast required)
- **Data**: `./data/` persists across restarts/rebuilds
  - `devices.db` - SQLite database
  - `encryption.key` - Fernet encryption key
- **Stack**: Flask + python-kasa + APScheduler
- **Timezone**: Configurable via `TZ` environment variable (default: America/Edmonton)

## Developer Commands

```bash
# Rebuild after code changes
docker compose down && docker compose up --build -d

# Just restart (preserves data)
docker compose restart

# View logs
docker logs flowboard

# View app logs inside container
docker exec flowboard tail -20 /data/app.log

# Clear database and start fresh (WARNING: loses all data)
rm data/devices.db && docker compose up --build -d
```

## Adding Kasa Devices

1. Click **"+ Account"** to add your Kasa credentials (email + password)
2. Select the account from the dropdown
3. Click **"Scan"** to discover devices on your network (uses UDP broadcast)
4. Or click **"Add Device"** to add by IP address manually
5. Toggle devices on/off from the UI

## Features

- Multi-user support with encrypted credentials
- HS300 (6-plug strips) shown as separate devices
- Credentials encrypted with Fernet (AES-128)
- Background scheduler for automated device control
- Event logging for all device state changes
- Sequential device refresh with real-time progress
- Activity log with filtering/sorting

## Scheduler

### New Design (v2)

The scheduler was redesigned to support rack/shelf/device level scheduling:

- **Target Types**: `rack`, `shelf`, `device`
- **Schedule Types**:
  - `on` - Turn on at specific time
  - `off` - Turn off at specific time  
  - `on_then_off` - Turn on, then off after duration (H:M:S)
  - `cycle` - Cycle on/off continuously (placeholder)

### API Endpoints

```
GET    /api/schedules              - List all schedules
POST   /api/schedules              - Create new schedule
PUT    /api/schedules/<id>         - Update schedule
DELETE /api/schedules/<id>         - Delete schedule
```

### Schedule Payload

```json
{
  "name": "Morning Lights",
  "target_type": "shelf",
  "target_id": 1,
  "schedule_type": "on",
  "start_hour": 6,
  "start_minute": 0,
  "duration_seconds": 0,
  "off_duration_seconds": 0,
  "days": "0,1,2,3,4,5,6",
  "enabled": 1
}
```

## Device Communication (Important)

### Discovery Method

**UDP broadcast discovery** is used (port 9999). This requires `network_mode: host` in Docker.

- ❌ KLAP V2: `Device response did not match our challenge` - authentication fails
- ✅ UDP Broadcast (port 9999): Works correctly

Key finding: Devices can be discovered without credentials (UDP broadcast), but control requires credentials with port 9999.

```python
# Discovery without credentials (works via UDP broadcast)
disc = Discover()
found = await disc.discover()

# Control with credentials and port 9999
plug = await Discover.discover_single(ip, credentials=credentials, port=9999)
```

### Performance

- **Toggle latency**: ~3-4 seconds per toggle operation
- **Device refresh**: Sequential with 2-second delays between devices
- **Retry logic**: 4 retries with 1s, 2s, 5s delays
- This is **normal** - it's the network latency to communicate with Kasa devices

## Configuration

### Timezone

Set via environment variable in docker-compose.yml:
```yaml
environment:
  - TZ=America/Edmonton
```

### Retry Configuration

Defined in `backend/constants.py`:
```python
MAX_RETRIES = 4
RETRY_DELAYS = [1.0, 2.0, 5.0]  # seconds
```

## Database Migrations

The system includes automatic migrations that run on startup. To force a fresh database:
```bash
rm data/devices.db
docker compose up --build -d
```

## Known Issues

- Always install `tzdata` to prevent timezone errors
- HS300 (hardware version 1.0) with python-kasa v0.10.2 has KLAP V2 incompatibility - use port 9999
- Device discovery without credentials uses UDP broadcast which requires host network mode