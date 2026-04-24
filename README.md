# FlowBoard - EBB Flow Controller

A web-based smart home controller for Kasa smart outlets and ESP32 sensors, designed for grow systems and home automation.

## Features

- **Smart Device Management**: Control Kasa smart plugs, lights, pumps, and aerators
- **ESP32 Sensor Integration**: Monitor temperature, humidity, and other sensors
- **Rack/Shelf Organization**: Organize devices and sensors by physical location
- **Automated Scheduling**: Schedule devices to turn on/off at specific times
- **Real-time Dashboard**: Monitor all devices and sensors from a single page
- **Activity Logging**: Track all device operations with timestamps
- **Multi-user Support**: Encrypted credentials for multiple Kasa accounts

## Quick Start

```bash
docker compose up --build -d  # Start the application
docker logs flowboard         # View logs
docker compose down           # Stop
```

Access the dashboard at http://localhost:9731

## Documentation

- [AGENTS.md](AGENTS.md) - Developer guide and API documentation
- [SPEC.md](SPEC.md) - Detailed specification and architecture

## Key Details

- **Port**: 9731
- **Network**: Uses `network_mode: host` for Kasa device discovery
- **Data**: Persisted in `./data/` directory
- **Timezone**: Configurable via `TZ` environment variable (default: America/Edmonton)

## Components

- **Backend**: Flask + python-kasa + APScheduler
- **Frontend**: Vanilla JavaScript single-page application
- **Database**: SQLite
- **Deployment**: Docker Compose

## License

MIT
