"""
Shared helper functions for FlowBoard.
"""
from typing import Optional, Tuple
from backend.database import db
from backend.constants import LOCAL_TZ
from kasa import Credentials


def get_account_credentials(account_id: int) -> Optional[Credentials]:
    """Get Kasa credentials for an account."""
    if not account_id:
        return None
    
    from cryptography.fernet import Fernet
    import os
    
    # Get encryption key
    if os.path.exists('/data/encryption.key'):
        with open('/data/encryption.key', 'rb') as f:
            key = f.read()
    else:
        key = Fernet.generate_key()
        with open('/data/encryption.key', 'wb') as f:
            f.write(key)
    
    f = Fernet(key)
    
    with db() as database:
        account = database.fetch_one('SELECT * FROM accounts WHERE id = ?', (account_id,))
        if not account:
            return None
        
        if account['provider'] in ('kasa', 'tapo'):
            username = account['username_encrypted']
            password = account['password_encrypted']
            
            if username and password:
                try:
                    username = f.decrypt(username.encode()).decode()
                    password = f.decrypt(password.encode()).decode()
                    return Credentials(username=username, password=password)
                except:
                    pass
    
    return None


def get_device_rack_shelf(device_id: int) -> Tuple[Optional[str], Optional[str]]:
    """Get the current rack and shelf name for a device."""
    with db() as database:
        result = database.fetch_one('''
            SELECT r.name as rack_name, s.name as shelf_name
            FROM components c
            JOIN shelves s ON s.id = c.parent_id AND c.parent_type = 'shelf'
            JOIN racks r ON r.id = s.rack_id
            WHERE c.device_id = ?
            LIMIT 1
        ''', (device_id,))
        if result:
            return (result['rack_name'], result['shelf_name'])
        return (None, None)