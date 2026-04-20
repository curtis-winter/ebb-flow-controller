"""
Database utility module for FlowBoard.
Provides connection management and helper functions.
"""
import sqlite3
from contextlib import contextmanager

DB_PATH = '/data/devices.db'

def get_db():
    """Create a new database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

class Database:
    """Utility class for database operations with context manager support."""
    
    def __init__(self):
        self.conn = None
    
    def __enter__(self):
        self.conn = get_db()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()
        return False
    
    def fetch_one(self, query, params=None):
        """Fetch a single row."""
        params = params or ()
        return self.conn.execute(query, params).fetchone()
    
    def fetch_all(self, query, params=None):
        """Fetch all rows."""
        params = params or ()
        return self.conn.execute(query, params).fetchall()
    
    def execute(self, query, params=None):
        """Execute a query."""
        params = params or ()
        return self.conn.execute(query, params)
    
    def commit(self):
        """Commit the current transaction."""
        self.conn.commit()
    
    @staticmethod
    def dict(row):
        """Convert a row to a dictionary."""
        return dict(row) if row else None

def db():
    """Convenience function to create a Database instance."""
    return Database()

def init_schema():
    """Initialize the database schema."""
    with db() as database:
        # Accounts table
        database.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'kasa',
                username_encrypted TEXT,
                password_encrypted TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Devices table
        database.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                name TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                mac_address TEXT,
                model TEXT,
                child_id TEXT,
                is_on INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        ''')
        
        # Activity log table
        database.execute('''
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER,
                device_name TEXT,
                action_type TEXT NOT NULL,
                details TEXT,
                rack_name TEXT,
                shelf_name TEXT,
                device_response TEXT,
                device_status TEXT,
                trigger_source TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES devices(id)
            )
        ''')
        
        # Add details column if it doesn't exist
        try:
            database.execute('ALTER TABLE activity_log ADD COLUMN details TEXT')
        except:
            pass
        
        # Add rack_name and shelf_name columns if they don't exist
        try:
            database.execute('ALTER TABLE activity_log ADD COLUMN rack_name TEXT')
        except:
            pass
        try:
            database.execute('ALTER TABLE activity_log ADD COLUMN shelf_name TEXT')
        except:
            pass
        
        # Add device_response and device_status columns if they don't exist
        try:
            database.execute('ALTER TABLE activity_log ADD COLUMN device_response TEXT')
        except:
            pass
        try:
            database.execute('ALTER TABLE activity_log ADD COLUMN device_status TEXT')
        except:
            pass
        
        # Add trigger_source column if it doesn't exist
        try:
            database.execute('ALTER TABLE activity_log ADD COLUMN trigger_source TEXT')
        except:
            pass
        
        # Racks table
        database.execute('''
            CREATE TABLE IF NOT EXISTS racks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Shelves table
        database.execute('''
            CREATE TABLE IF NOT EXISTS shelves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rack_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                position INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (rack_id) REFERENCES racks(id) ON DELETE CASCADE
            )
        ''')
        
        # Reservoirs table
        database.execute('''
            CREATE TABLE IF NOT EXISTS reservoirs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rack_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                position INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (rack_id) REFERENCES racks(id) ON DELETE CASCADE
            )
        ''')
        
        # Components table
        database.execute('''
            CREATE TABLE IF NOT EXISTS components (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_type TEXT NOT NULL,
                parent_id INTEGER NOT NULL,
                device_id INTEGER,
                component_type TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES devices(id)
            )
        ''')
        
        # Schedules table
        database.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'on',
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL,
                days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
            )
        ''')
        
        database.commit()
