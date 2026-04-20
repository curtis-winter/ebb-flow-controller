"""
Retry decorator and utilities for async functions.
"""
import asyncio
import logging
from functools import wraps
from typing import Callable, Tuple, Any, Optional
from backend.constants import MAX_RETRIES, RETRY_DELAYS

logger = logging.getLogger(__name__)


def with_retry(
    max_retries: int = MAX_RETRIES,
    retry_delays: list = RETRY_DELAYS,
    default_return: Any = None,
):
    """
    Decorator to add retry logic to async functions.
    
    Args:
        max_retries: Maximum number of retry attempts
        retry_delays: List of delays between retries (in seconds)
        default_return: Value to return if all retries fail
    
    Usage:
        @with_retry()
        async def my_function():
            ...
            return result
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = retry_delays[attempt] if attempt < len(retry_delays) else retry_delays[-1]
                        logger.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}, retrying in {delay}s")
                        await asyncio.sleep(delay)
            
            logger.error(f"{func.__name__} failed after {max_retries} attempts: {last_error}")
            return default_return
        
        return wrapper
    return decorator


def with_retry_sync(
    max_retries: int = MAX_RETRIES,
    retry_delays: list = RETRY_DELAYS,
    default_return: Any = None,
):
    """
    Decorator to add retry logic to sync functions.
    
    Args:
        max_retries: Maximum number of retry attempts
        retry_delays: List of delays between retries (in seconds)
        default_return: Value to return if all retries fail
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import time
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = retry_delays[attempt] if attempt < len(retry_delays) else retry_delays[-1]
                        logger.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}, retrying in {delay}s")
                        time.sleep(delay)
            
            logger.error(f"{func.__name__} failed after {max_retries} attempts: {last_error}")
            return default_return
        
        return wrapper
    return decorator


async def execute_with_retry(
    coro: Callable,
    max_retries: int = MAX_RETRIES,
    retry_delays: list = RETRY_DELAYS,
) -> Tuple[Any, int]:
    """
    Execute a coroutine with retry logic.
    Returns (result, retries_used) tuple.
    """
    last_error = None
    retries_used = 0
    
    for attempt in range(max_retries):
        try:
            result = await coro()
            return (result, retries_used)
        except Exception as e:
            last_error = e
            retries_used = attempt + 1
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                delay = retry_delays[attempt] if attempt < len(retry_delays) else retry_delays[-1]
                await asyncio.sleep(delay)
    
    logger.error(f"Failed after {max_retries} attempts: {last_error}")
    return (None, retries_used)