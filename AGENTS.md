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

## Known Issues

- Always install `tzdata` to prevent timezone errors

## Device Communication (Important)

### Discovery Method

After testing, we found that **KLAP V2 does NOT work** with your devices, but **port 9999 discovery works**:

- ❌ KLAP V2: `Device response did not match our challenge` - authentication fails
- ✅ Port 9999: Works correctly

The device service uses port 9999 discovery exclusively:

```python
# In backend/services/device_service.py
async def _get_plug(credentials, parent_ip):
    plug = await Discover.discover_single(parent_ip, credentials=credentials, port=9999)
    await plug.update()
    return plug
```

### Performance

- **Toggle latency**: ~3-4 seconds per toggle operation
- This is **normal** - it's the network latency to communicate with Kasa devices
- There's no way to make it faster since it's a limitation of the device itself

### Why Not KLAP V2?

Your HS300 (hardware version 1.0) and python-kasa v0.10.2 have incompatibility issues with KLAP V2 authentication. The error message is:
```
Device response did not match our challenge on ip X.X.X.X, check that your e-mail and password (both case-sensitive) are correct.
```

This happens even with correct credentials because the authentication protocol differs between versions.