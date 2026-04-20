"""
Constants for FlowBoard application.
"""
from zoneinfo import ZoneInfo

# Timezone
EDMONTON_TZ: ZoneInfo = ZoneInfo('America/Edmonton')

# Retry configuration
MAX_RETRIES: int = 3
RETRY_DELAYS: list[float] = [0.5, 1.5]

# Action types
ACTION_TYPES: dict[str, str] = {
    'TOGGLE': 'device_toggle',
    'REFRESH': 'device_status_refresh',
}

# Device status values
DEVICE_STATUS: dict[str, str] = {
    'SUCCESS': 'success',
    'FAILED': 'failed',
    'ERROR': 'error',
}

# Trigger source values
TRIGGER_SOURCE: dict[str, str] = {
    'MANUAL': 'Manual',
    'SCHEDULED': 'Scheduled',
}