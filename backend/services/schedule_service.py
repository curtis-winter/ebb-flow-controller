"""
Schedule service for managing automated device actions.
"""
import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from backend.constants import EDMONTON_TZ
from backend.database import db
from backend.services.device_service import get_device_state, toggle_device_state
from backend.services.activity_log_service import log_toggle

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler = BackgroundScheduler()


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
            SELECT s.*, d.account_id, d.child_id, d.ip_address, d.name as device_name
            FROM schedules s
            JOIN devices d ON s.device_id = d.id
            WHERE s.enabled = 1
        ''')
    
    from backend.app import get_account_credentials, get_device_rack_shelf
    
    for schedule in schedules:
        days = [int(d) for d in schedule['days'].split(',')]
        
        # Check if today matches the schedule
        if current_day not in days:
            continue
        
        # Check if time matches
        if schedule['hour'] != current_hour or schedule['minute'] != current_minute:
            continue
        
        action = schedule['action']
        device_id = schedule['device_id']
        account_id = schedule['account_id']
        child_id = schedule['child_id']
        ip_address = schedule['ip_address']
        device_name = schedule['device_name']
        
        credentials = get_account_credentials(account_id) if account_id else None
        rack_name, shelf_name = get_device_rack_shelf(device_id)
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            desired_state = action == 'on'
            current_state, retries = loop.run_until_complete(
                get_device_state(credentials, ip_address, child_id)
            )
            
            if current_state != desired_state:
                state, retries = loop.run_until_complete(
                    toggle_device_state(credentials, ip_address, child_id, desired_state)
                )
                
                log_toggle(
                    device_id=device_id,
                    device_name=device_name,
                    device_response='ON' if state else 'OFF',
                    device_status='success' if state is not None else 'failed',
                    trigger_source='Scheduled',
                    rack_name=rack_name,
                    shelf_name=shelf_name,
                    retries=retries,
                )
                
                logger.info(f"Schedule {schedule['id']}: Turned device {device_id} {action}")
            
            loop.close()
            
        except Exception as e:
            logger.error(f"Schedule {schedule['id']} error: {e}")
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