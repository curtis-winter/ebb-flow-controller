# Smart Outlet Controller - Specification

## Project Overview
- **Project Name**: EBB Flow Controller
- **Type**: Web Application (Docker deployed)
- **Core Functionality**: Manage multiple Kasa brand WiFi smart outlets through a web interface
- **Target Users**: Home users managing smart home devices

## Architecture

### Technology Stack
- **Backend**: Python Flask + Kasa library
- **Frontend**: Single-page HTML/JS with vanilla JS
- **Database**: SQLite (for device persistence)
- **Deployment**: Docker Compose

### Components
1. **Backend API** (Flask): REST API to discover and control Kasa devices
2. **Frontend**: Web dashboard to view and control outlets
3. **Database**: Stores device configurations

## Functionality Specification

### Core Features

#### Device Discovery
- Scan network for Kasa smart outlets using UDP broadcast
- Add devices manually by IP address
- Store discovered devices in database

#### Device Control
- Toggle outlet on/off
- View current on/off state
- View device info (name, IP, model, MAC)

#### Device Management
- Edit device friendly names
- Remove devices from control
- Refresh device status

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

### Data Model

#### Device
```
- id: INTEGER PRIMARY KEY
- name: VARCHAR (friendly name)
- ip_address: VARCHAR (device IP)
- mac_address: VARCHAR (device MAC)
- model: VARCHAR (device model)
- created_at: TIMESTAMP
```

## UI/UX Specification

### Layout Structure
- Single page dashboard
- Header with app title
- Grid of device cards
- "Discover Devices" button in header
- "Add Device" form (modal)

### Responsive Breakpoints
- Mobile: < 640px (1 column)
- Tablet: 640px - 1024px (2 columns)
- Desktop: > 1024px (3 columns)

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
- App Title: 24px
- Card Title: 18px
- Card Body: 14px

#### Spacing
- Card padding: 20px
- Card gap: 20px
- Container padding: 24px

#### Visual Effects
- Cards: subtle box-shadow, 8px border-radius
- Buttons: 6px border-radius, transition on hover
- Toggle: smooth 0.2s transition
- Card hover: slight scale transform (1.02)

### Components

#### Device Card
- Device icon (plug emoji or SVG)
- Device name (editable display)
- Current state indicator (green/red badge)
- IP address display
- Toggle button
- Delete button (icon)

#### Header
- App title "EBB Flow Controller"
- "Discover Devices" button
- "Add Device" button

#### Add Device Modal
- IP address input field
- "Add" and "Cancel" buttons
- Overlay backdrop

#### Discover Modal
- Loading spinner during discovery
- List of found devices with checkboxes
- "Add Selected" button

## Acceptance Criteria

1. Docker Compose successfully starts backend and serves frontend
2. Can discover Kasa devices on local network
3. Can add device by IP address
4. Can toggle device on/off from web interface
5. Device state updates reflect actual device state
6. Devices persist across container restarts
7. UI is responsive on mobile and desktop
8. Visual design matches color palette specification