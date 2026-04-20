"""
Constants for FlowBoard application.
"""
import os
from zoneinfo import ZoneInfo

# Timezone - read from environment variable or default to America/Edmonton
TZ_NAME: str = os.environ.get('TZ', 'America/Edmonton')
LOCAL_TZ: ZoneInfo = ZoneInfo(TZ_NAME)

# Backwards compatibility alias
EDMONTON_TZ = LOCAL_TZ

# Retry configuration
MAX_RETRIES: int = 4
RETRY_DELAYS: list[float] = [1.0, 2.0, 5.0]

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