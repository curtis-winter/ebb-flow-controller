"""
Schedule service for managing automated device actions.
Supports rack, shelf, and device level schedules with multiple schedule types.
"""
import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from backend.constants import LOCAL_TZ
from backend.database import db, Database
from backend.services.device_service import get_device_state, toggle_device_state
from backend.services.activity_log_service import log_toggle
from backend.services.helpers import get_account_credentials, get_device_rack_shelf

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler = BackgroundScheduler()


def get_devices_for_target(target_type: str, target_id: int) -> list:
    """Get all devices associated with a target (rack, shelf, or device)."""
    with db() as database:
        if target_type == 'device':
            device = database.fetch_one('SELECT * FROM devices WHERE id = ?', (target_id,))
            return [dict(Database.dict(device))] if device else []
        
        elif target_type == 'shelf':
            devices = database.fetch_all('''
                SELECT d.* FROM devices d
                JOIN components c ON c.device_id = d.id
                WHERE c.parent_type = 'shelf' AND c.parent_id = ?
            ''', (target_id,))
            return [Database.dict(d) for d in devices]
        
        elif target_type == 'rack':
            devices = database.fetch_all('''
                SELECT d.* FROM devices d
                JOIN components c ON c.device_id = d.id
                JOIN shelves s ON s.id = c.parent_id AND c.parent_type = 'shelf'
                WHERE s.rack_id = ?
            ''', (target_id,))
            return [Database.dict(d) for d in devices]
    
    return []


def check_schedules() -> None:
    """
    Check and execute schedules that match the current time.
    This function is called by the APScheduler every minute.
    """
    now = datetime.now()
    current_day = now.weekday()
    current_hour = now.hour
    current_minute = now.minute
    
    with db() as database:
        schedules = database.fetch_all('''
            SELECT * FROM schedules WHERE enabled = 1
        ''')
    
    for schedule in schedules:
        days = [int(d) for d in schedule['days'].split(',')]
        
        # Check if today matches the schedule
        if current_day not in days:
            continue
        
        # Check if time matches
        if schedule['start_hour'] != current_hour or schedule['start_minute'] != current_minute:
            continue
        
        target_type = schedule['target_type']
        target_id = schedule['target_id']
        schedule_type = schedule['schedule_type']
        schedule_name = schedule['name']
        
        # Get devices for this target
        devices = get_devices_for_target(target_type, target_id)
        
        for device in devices:
            _execute_schedule_action(
                device=device,
                schedule_type=schedule_type,
                schedule_name=schedule_name,
                duration_seconds=schedule.get('duration_seconds', 0),
                off_duration_seconds=schedule.get('off_duration_seconds', 0),
            )


def _execute_schedule_action(
    device: dict,
    schedule_type: str,
    schedule_name: str,
    duration_seconds: int = 0,
    off_duration_seconds: int = 0,
) -> None:
    """Execute a schedule action for a device."""
    
    device_id = device['id']
    device_name = device['name']
    account_id = device['account_id']
    child_id = device['child_id']
    ip_address = device['ip_address']
    
    credentials = get_account_credentials(account_id) if account_id else None
    rack_name, shelf_name = get_device_rack_shelf(device_id)
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        if schedule_type == 'on':
            # Turn on
            state, retries = loop.run_until_complete(
                toggle_device_state(credentials, ip_address, child_id, True)
            )
            log_toggle(
                device_id=device_id,
                device_name=device_name,
                device_response='ON' if state else 'OFF',
                device_status='success' if state else 'failed',
                trigger_source='Scheduled',
                rack_name=rack_name,
                shelf_name=shelf_name,
                retries=retries,
            )
            
        elif schedule_type == 'off':
            # Turn off
            state, retries = loop.run_until_complete(
                toggle_device_state(credentials, ip_address, child_id, False)
            )
            log_toggle(
                device_id=device_id,
                device_name=device_name,
                device_response='ON' if state else 'OFF',
                device_status='success' if state else 'failed',
                trigger_source='Scheduled',
                rack_name=rack_name,
                shelf_name=shelf_name,
                retries=retries,
            )
            
        elif schedule_type == 'on_then_off':
            # Turn on now, turn off after duration
            # First turn on
            state, retries = loop.run_until_complete(
                toggle_device_state(credentials, ip_address, child_id, True)
            )
            log_toggle(
                device_id=device_id,
                device_name=device_name,
                device_response='ON',
                device_status='success' if state else 'failed',
                trigger_source='Scheduled',
                rack_name=rack_name,
                shelf_name=shelf_name,
                retries=retries,
            )
            
            # Schedule turn off
            if duration_seconds > 0:
                async def delayed_off():
                    await asyncio.sleep(duration_seconds)
                    state, retries = await toggle_device_state(credentials, ip_address, child_id, False)
                    log_toggle(
                        device_id=device_id,
                        device_name=device_name,
                        device_response='OFF',
                        device_status='success' if state else 'failed',
                        trigger_source='Scheduled',
                        rack_name=rack_name,
                        shelf_name=shelf_name,
                        retries=retries,
                    )
                
                loop.run_until_complete(delayed_off())
            
        elif schedule_type == 'cycle':
            # Cycle on/off - handled by separate scheduled tasks
            # This is more complex and would need additional logic
            logger.warning(f"Cycle schedule type not fully implemented: {schedule_name}")
        
        loop.close()
        logger.info(f"Executed {schedule_type} for device {device_id} ({device_name})")
        
    except Exception as e:
        logger.error(f"Schedule error for device {device_id}: {e}")
        log_toggle(
            device_id=device_id,
            device_name=device_name,
            device_response=None,
            device_status='error',
            trigger_source='Scheduled',
            rack_name=rack_name,
            shelf_name=shelf_name,
            retries=0,
        )


def start_scheduler() -> None:
    """Start the background scheduler."""
    _scheduler.add_job(
        func=check_schedules,
        trigger='cron',
        second=0
    )
    _scheduler.start()
    logger.info("Background scheduler started")


def stop_scheduler() -> None:
    """Stop the background scheduler."""
    _scheduler.shutdown()