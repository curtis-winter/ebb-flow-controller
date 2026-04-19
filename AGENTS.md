# EBB Flow Controller

## Quick Start

```bash
docker compose up --build -d   # Build and start
docker logs ebb-flow-controller # View logs
docker compose down            # Stop
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
docker logs ebb-flow-controller
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

## Known Issues

- HS300 v2.0 (hardware version 2.0) with KLAP authentication may require python-kasa dev branch for full support