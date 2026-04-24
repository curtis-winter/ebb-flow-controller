"""
Activity log service for FlowBoard.
Handles all activity logging with consistent structure.
"""
import logging
from datetime import datetime
from typing import Optional
from backend.database import db
from backend.constants import LOCAL_TZ

logger = logging.getLogger(__name__)


def log_activity(
    device_id: int,
    device_name: str,
    action_type: str,
    device_response: Optional[str] = None,
    device_status: str = 'success',
    trigger_source: str = 'Manual',
    rack_name: Optional[str] = None,
    shelf_name: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """
    Log an activity to the activity_log table.
    """
    timestamp = datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
    
    # Ensure we handle None values properly for SQL
    device_response = device_response if device_response else 'N/A'
    device_status = device_status if device_status else 'unknown'
    trigger_source = trigger_source if trigger_source else 'Manual'
    rack_name = rack_name if rack_name else ''
    shelf_name = shelf_name if shelf_name else ''
    details = details if details else ''
    
    try:
        with db() as database:
            database.execute(
                'INSERT INTO activity_log (timestamp, device_id, device_name, action_type, device_response, device_status, trigger_source, rack_name, shelf_name, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (timestamp, device_id, device_name, action_type, device_response, device_status, trigger_source, rack_name, shelf_name, details)
            )
            database.commit()
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")


def log_toggle(
    device_id: int,
    device_name: str,
    device_response: Optional[str],
    device_status: str,
    trigger_source: str,
    rack_name: Optional[str] = None,
    shelf_name: Optional[str] = None,
    retries: int = 0,
) -> None:
    """Log a device toggle action."""
    details = f"retries:{retries}" if retries > 0 else "retries:0"
    log_activity(
        device_id=device_id,
        device_name=device_name,
        action_type='device_toggle',
        device_response=device_response,
        device_status=device_status,
        trigger_source=trigger_source,
        rack_name=rack_name,
        shelf_name=shelf_name,
        details=details,
    )


def log_refresh(
    device_id: int,
    device_name: str,
    device_response: Optional[str],
    device_status: str,
    rack_name: Optional[str] = None,
    shelf_name: Optional[str] = None,
    retries: int = 0,
    error: Optional[str] = None,
) -> None:
    """Log a device status refresh action."""
    details = error or (f"retries:{retries}" if retries > 0 else "retries:0")
    log_activity(
        device_id=device_id,
        device_name=device_name,
        action_type='device_status_refresh',
        device_response=device_response,
        device_status=device_status,
        trigger_source='Manual',
        rack_name=rack_name,
        shelf_name=shelf_name,
        details=details,
    )