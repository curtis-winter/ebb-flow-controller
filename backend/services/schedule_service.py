"""
Schedule service for managing automated device actions.
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler = BackgroundScheduler()

def get_device_service():
    """Lazy import to avoid circular dependencies."""
    from backend.services.device_service import get_device_state, toggle_device_state
    return get_device_state, toggle_device_state

def get_account_credentials_func():
    """Lazy import of account credentials function."""
    from backend.app import get_account_credentials
    return get_account_credentials

def get_device_rack_shelf_func():
    """Lazy import to avoid circular dependencies."""
    from backend.app import get_device_rack_shelf
    return get_device_rack_shelf

def check_schedules():
    """
    Check and execute schedules that match the current time.
    This function is called by the APScheduler every minute.
    """
    from backend.database import db, Database
    
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
    
    get_creds = get_account_credentials_func()
    get_state, toggle_state = get_device_service()
    get_rack_shelf = get_device_rack_shelf_func()
    
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
        
        credentials = get_creds(account_id) if account_id else None
        rack_name, shelf_name = get_rack_shelf(device_id)
        
        # Use Edmonton timezone for timestamp
        edmonton_tz = ZoneInfo('America/Edmonton')
        timestamp = datetime.now(edmonton_tz).strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            desired_state = action == 'on'
            current_state, retries = loop.run_until_complete(
                get_state(credentials, ip_address, child_id)
            )
            
            if current_state != desired_state:
                state, retries = loop.run_until_complete(
                    toggle_state(credentials, ip_address, child_id, desired_state)
                )
                
                details = f"retries:{retries}" if retries > 0 else "retries:0"
                device_response = 'ON' if state else 'OFF'
                device_status = 'success' if state is not None else 'failed'
                
                with db() as database:
                    database.execute(
                        'INSERT INTO activity_log (timestamp, device_id, device_name, action_type, details, rack_name, shelf_name, device_response, device_status, trigger_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (timestamp, device_id, device_name, 'device_toggle', details, rack_name, shelf_name, device_response, device_status, 'Scheduled')
                    )
                    database.commit()
                
                logger.info(f"Schedule {schedule['id']}: Turned device {device_id} {action}")
            
            loop.close()
            
        except Exception as e:
            logger.error(f"Schedule {schedule['id']} error: {e}")
            with db() as database:
                database.execute(
                    'INSERT INTO activity_log (timestamp, device_id, device_name, action_type, details, rack_name, shelf_name, device_response, device_status, trigger_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (timestamp, device_id, device_name, 'device_toggle', f"error:{str(e)}", rack_name, shelf_name, 'N/A', 'error', 'Scheduled')
                )
                database.commit()

def start_scheduler():
    """Start the background scheduler."""
    _scheduler.add_job(
        func=check_schedules,
        trigger='cron',
        second=0
    )
    _scheduler.start()
    logger.info("Background scheduler started")

def stop_scheduler():
    """Stop the background scheduler."""
    _scheduler.shutdown()
