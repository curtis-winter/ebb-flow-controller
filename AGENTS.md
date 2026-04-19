# FlowBoard

## Quick Start

```bash
docker compose up --build -d   # Build and start
docker logs flowboard         # View logs
docker compose down         # Stop
```

## Key Details

- **Port**: 9731
- **Network**: Uses `network_mode: host` for Kasa device discovery
- **Data**: `./data/` persists across restarts/rebuilds
  - `devices.db` - SQLite database
  - `encryption.key` - Fernet encryption key
- **Stack**: Flask + python-kasa (v0.10.2)

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
```

## Adding Kasa Devices

1. Click **"+ Account"** to add your Kasa credentials (email + password)
2. Select the account from the dropdown
3. Click **"Scan"** to discover devices on your network
4. Or click **"Add Device"** to add by IP address
5. Toggle devices on/off from the UI

## Features

- Multi-user support with encrypted credentials
- HS300 (6-plug strips) shown as separate devices
- Credentials encrypted with Fernet (AES-128)
- Background scheduler for automated device control
- Event logging for external state changes

## KLAP V2 Authentication (Required for HS300 v2.0)

The python-kasa library requires specific imports and setup for KLAP V2 authentication:

```python
# Required imports for KLAP V2
from kasa.transports.klaptransport import KlapTransportV2
from kasa.protocols import IotProtocol
from kasa.iot import IotStrip
from kasa.deviceconfig import DeviceConfig

# Usage pattern:
config = DeviceConfig(host=ip_address, credentials=credentials)
protocol = IotProtocol(transport=KlapTransportV2(config=config))
plug = IotStrip(host=ip_address, protocol=protocol)
await plug.update()
```

### Critical Dependencies

When using KLAP V2, you **must** install `tzdata`:

```dockerfile
RUN pip install --no-cache-dir -r backend/requirements.txt tzdata
```

Without `tzdata`, you'll see errors like:
- `ZoneInfoNotFoundError: 'No time zone found with key MST7MDT'`
- `Device response did not match our challenge`

### Install PR 1625 for KLAP Fixes

Some KLAP devices require the dev branch fix:

```dockerfile
RUN pip install --no-cache-dir "git+https://github.com/python-kasa/python-kasa.git@refs/pull/1625/head" --no-deps --force-reinstall
```

## Known Issues

- HS300 v2.0 (hardware version 2.0) may require python-kasa PR 1625 for full KLAP V2 support
- Always install `tzdata` to prevent timezone errors