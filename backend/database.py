"""
Database utility module for FlowBoard.
Provides connection management, schema initialization, and migrations.
"""
import sqlite3
from contextlib import contextmanager

DB_PATH = '/data/devices.db'

# Schema version - increment when making schema changes
SCHEMA_VERSION = 2


def get_db() -> sqlite3.Connection:
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
    
    def fetch_one(self, query: str, params: tuple = None) -> sqlite3.Row:
        """Fetch a single row."""
        params = params or ()
        return self.conn.execute(query, params).fetchone()
    
    def fetch_all(self, query: str, params: tuple = None) -> list:
        """Fetch all rows."""
        params = params or ()
        return self.conn.execute(query, params).fetchall()
    
    def execute(self, query: str, params: tuple = None) -> sqlite3.Cursor:
        """Execute a query."""
        params = params or ()
        return self.conn.execute(query, params)
    
    def commit(self) -> None:
        """Commit the current transaction."""
        self.conn.commit()
    
    @staticmethod
    def dict(row: sqlite3.Row) -> dict:
        """Convert a row to a dictionary."""
        return dict(row) if row else None


def db() -> Database:
    """Convenience function to create a Database instance."""
    return Database()


def column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    try:
        with db() as database:
            result = database.fetch_one(f"PRAGMA table_info({table})")
            if result:
                columns = [row['name'] for row in database.fetch_all(f"PRAGMA table_info({table})")]
                return column in columns
            return False
    except Exception:
        return False


def table_exists(table: str) -> bool:
    """Check if a table exists."""
    try:
        with db() as database:
            result = database.fetch_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            return result is not None
    except Exception:
        return False


def get_schema_version() -> int:
    """Get the current schema version from the database."""
    if not table_exists('schema_version'):
        return 0
    
    try:
        with db() as database:
            result = database.fetch_one('SELECT version FROM schema_version ORDER BY version DESC LIMIT 1')
            return result['version'] if result else 0
    except Exception:
        return 0


def set_schema_version(version: int) -> None:
    """Set the schema version in the database."""
    with db() as database:
        database.execute('INSERT INTO schema_version (version) VALUES (?)', (version,))
        database.commit()


def migrate_schema() -> None:
    """Run migrations to update the schema."""
    current_version = get_schema_version()

    if current_version < 1:
        migrate_to_v1()

    if current_version < 2:
        migrate_to_v2()
    
    if current_version < 3:
        migrate_to_v3()


def migrate_to_v3() -> None:
    """Add rack_id and shelf_id to esp32_sensors."""
    add_column_if_not_exists('esp32_sensors', 'rack_id', 'INTEGER')
    add_column_if_not_exists('esp32_sensors', 'shelf_id', 'INTEGER')
    set_schema_version(3)
    print("Migrated to v3: Added rack_id/shelf_id to esp32_sensors")


def migrate_to_v1() -> None:
    """Initial schema setup."""
    with db() as database:
        # Schema version table
        database.execute('''
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
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
                last_updated TEXT,
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
        
        # Schedules table - new design for rack/shelf/device levels
        database.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                schedule_type TEXT NOT NULL,
                start_hour INTEGER NOT NULL,
                start_minute INTEGER NOT NULL,
                duration_seconds INTEGER DEFAULT 0,
                off_duration_seconds INTEGER DEFAULT 0,
                days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Schedule typesenum:
        # - on: Turn on at specific time
        # - off: Turn off at specific time
        # - on_then_off: Turn on at time, turn off after duration
        # - cycle: Cycle on/off with intervals
        
        database.commit()
        set_schema_version(1)
    
    # Run any column additions for existing databases
    migrate_add_columns()


def migrate_add_columns() -> None:
    """Add columns to existing tables if they don't exist."""
    add_column_if_not_exists('activity_log', 'details', 'TEXT')
    add_column_if_not_exists('activity_log', 'rack_name', 'TEXT')
    add_column_if_not_exists('activity_log', 'shelf_name', 'TEXT')
    add_column_if_not_exists('activity_log', 'device_response', 'TEXT')
    add_column_if_not_exists('activity_log', 'device_status', 'TEXT')
    add_column_if_not_exists('activity_log', 'trigger_source', 'TEXT')
    add_column_if_not_exists('devices', 'last_updated', 'TEXT')
    migrate_schedules_schema()


def migrate_schedules_schema() -> None:
    """Migrate schedules table to new schema while preserving data."""
    try:
        with db() as database:
            result = database.fetch_one("PRAGMA table_info(schedules)")
            if not result:
                return
                
            columns = [row['name'] for row in database.fetch_all("PRAGMA table_info(schedules)")]
            
            if 'target_type' not in columns:
                database.execute('ALTER TABLE schedules RENAME TO schedules_old')
                
                database.execute('''
                    CREATE TABLE schedules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        target_type TEXT NOT NULL,
                        target_id INTEGER NOT NULL,
                        schedule_type TEXT NOT NULL,
                        start_hour INTEGER NOT NULL,
                        start_minute INTEGER NOT NULL,
                        duration_seconds INTEGER DEFAULT 0,
                        off_duration_seconds INTEGER DEFAULT 0,
                        days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                        enabled INTEGER DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                old_schedules = database.fetch_all('SELECT * FROM schedules_old')
                action_map = {'on': 'on', 'off': 'off'}
                for old in old_schedules:
                    database.execute('''
                        INSERT INTO schedules (name, target_type, target_id, schedule_type, start_hour, start_minute, days, enabled)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        old['name'],
                        'device',
                        old['device_id'],
                        action_map.get(old['action'], 'on'),
                        old['hour'],
                        old['minute'],
                        old['days'],
                        old['enabled']
                    ))
                
                database.execute('DROP TABLE schedules_old')
                print("Migrated schedules to new schema")
    except Exception as e:
        print(f"Schedule migration: {e}")


def migrate_to_v2() -> None:
    """Add ESP32 sensor configuration tables."""
    with db() as database:
        database.execute('''
            CREATE TABLE IF NOT EXISTS esp32_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip_address TEXT,
                mac_address TEXT,
                is_active INTEGER DEFAULT 1,
                last_seen TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        database.execute('''
            CREATE TABLE IF NOT EXISTS esp32_sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                esp32_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                pin_number INTEGER NOT NULL,
                pin_mode TEXT DEFAULT 'INPUT',
                calibration_offset REAL DEFAULT 0.0,
                calibration_scale REAL DEFAULT 1.0,
                is_enabled INTEGER DEFAULT 1,
                rack_id INTEGER,
                shelf_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (esp32_id) REFERENCES esp32_devices(id) ON DELETE CASCADE,
                FOREIGN KEY (rack_id) REFERENCES racks(id) ON DELETE SET NULL,
                FOREIGN KEY (shelf_id) REFERENCES shelves(id) ON DELETE SET NULL
            )
        ''')
        
        database.execute('''
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                esp32_id INTEGER NOT NULL,
                sensor_id INTEGER,
                value REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (esp32_id) REFERENCES esp32_devices(id) ON DELETE CASCADE,
                FOREIGN KEY (sensor_id) REFERENCES esp32_sensors(id) ON DELETE SET NULL
            )
        ''')
        
        database.execute('''
            CREATE TABLE IF NOT EXISTS wifi_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ssid TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        database.commit()
        set_schema_version(2)
    print("Migrated to v2: ESP32 sensor tables created")


def add_column_if_not_exists(table: str, column: str, column_type: str) -> None:
    """Add a column to a table if it doesn't exist."""
    try:
        with db() as database:
            database.execute(f'ALTER TABLE {table} ADD COLUMN {column} {column_type}')
            database.commit()
    except Exception:
        pass  # Column likely already exists


def init_schema() -> None:
    """Initialize the database schema."""
    migrate_schema()


# Backwards compatibility
init_schema = init_schema