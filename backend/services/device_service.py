"""
Device service for managing Kasa smart devices.
Handles device discovery, state management, and toggling.
Uses port 9999 discovery (the only method that works with your devices).
Includes retry logic for reliability.
"""
import logging
import asyncio
from kasa import Discover, Credentials

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [0.5, 1.5]  # increasing delays: first retry=0.5s, second retry=1.5s

async def _get_plug(credentials, parent_ip):
    """Get a plug instance using port 9999 discovery."""
    plug = await Discover.discover_single(parent_ip, credentials=credentials, port=9999)
    await plug.update()
    return plug

async def get_device_state(credentials, parent_ip, child_id):
    """Get the current state of a device or child device with retry logic.
    Returns (state, retries_used) tuple."""
    last_error = None
    retries_used = 0
    
    for attempt in range(MAX_RETRIES):
        try:
            plug = await _get_plug(credentials, parent_ip)
            
            if child_id:
                for child in plug.children or []:
                    if child.device_id == child_id:
                        await child.update()
                        return (child.is_on, retries_used)
                return (None, retries_used)
            else:
                return (plug.is_on, retries_used)
                
        except Exception as e:
            last_error = e
            retries_used = attempt + 1
            logger.warning(f"Get state attempt {attempt + 1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
                await asyncio.sleep(delay)
    
    logger.error(f"Get state failed after {MAX_RETRIES} attempts: {last_error}")
    return (None, retries_used)

async def toggle_device_state(credentials, parent_ip, child_id, desired_state=None):
    """Toggle or set the state of a device with retry logic.
    Returns (state, retries_used) tuple."""
    last_error = None
    retries_used = 0
    
    for attempt in range(MAX_RETRIES):
        try:
            plug = await _get_plug(credentials, parent_ip)
            
            if child_id:
                child = None
                for c in plug.children or []:
                    if c.device_id == child_id:
                        child = c
                        break
                
                if not child:
                    return (None, retries_used)
                
                await child.update()
                
                if desired_state is not None:
                    if desired_state:
                        await child.turn_on()
                    else:
                        await child.turn_off()
                else:
                    await child.turn_on() if not child.is_on else await child.turn_off()
                
                await asyncio.sleep(0.3)
                await plug.update()
                
                for c in plug.children:
                    if c.device_id == child_id:
                        return (c.is_on, retries_used)
                return (None, retries_used)
            else:
                if desired_state is not None:
                    if desired_state:
                        await plug.turn_on()
                    else:
                        await plug.turn_off()
                else:
                    await plug.toggle()
                
                await plug.update()
                return (plug.is_on, retries_used)
                
        except Exception as e:
            last_error = e
            retries_used = attempt + 1
            logger.warning(f"Toggle attempt {attempt + 1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
                await asyncio.sleep(delay)
    
    logger.error(f"Toggle failed after {MAX_RETRIES} attempts: {last_error}")
    return (None, retries_used)

async def discover_device(ip_address, credentials=None):
    """Discover a device at the given IP address."""
    try:
        plug = await Discover.discover_single(ip_address, credentials=credentials, port=9999)
        await plug.update()
        return plug
    except Exception as e:
        logger.error(f"Discovery failed for {ip_address}: {e}")
        return None