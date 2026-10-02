import sqlite3

conn = sqlite3.connect("database.db")
cursor = conn.cursor()


# =========================
# USERS TABLE
# =========================

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
)
""")


# =========================
# FILES TABLE
# =========================

cursor.execute("""
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    owner_id INTEGER,
    FOREIGN KEY (owner_id) REFERENCES users(id)
)
""")


# Add owner_id if old table does not have it
columns = [
    row[1]
    for row in cursor.execute("PRAGMA table_info(files)").fetchall()
]

if "owner_id" not in columns:
    cursor.execute("""
    ALTER TABLE files
    ADD COLUMN owner_id INTEGER
    """)


# =========================
# FILE VERSIONS TABLE
# =========================

cursor.execute("""
CREATE TABLE IF NOT EXISTS file_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_by INTEGER,
    change_summary TEXT,
    FOREIGN KEY (modified_by) REFERENCES users(id)
)
""")


# Add new columns to old file_versions table
columns = [
    row[1]
    for row in cursor.execute(
        "PRAGMA table_info(file_versions)"
    ).fetchall()
]

if "modified_by" not in columns:
    cursor.execute("""
    ALTER TABLE file_versions
    ADD COLUMN modified_by INTEGER
    """)

if "change_summary" not in columns:
    cursor.execute("""
    ALTER TABLE file_versions
    ADD COLUMN change_summary TEXT
    """)


# =========================
# AUDIT LOGS TABLE
# =========================

cursor.execute("""
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    filename TEXT,
    log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")


# =========================
# FILE ACCESS / SHARING
# =========================

cursor.execute("""
CREATE TABLE IF NOT EXISTS file_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    permission TEXT NOT NULL DEFAULT 'view',
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(file_id, user_id)
)
""")


# =========================
# SYSTEM SETTINGS
# =========================

cursor.execute("""
CREATE TABLE IF NOT EXISTS system_settings (
    setting_name TEXT PRIMARY KEY,
    setting_value TEXT
)
""")


# =========================
# IST MIGRATION
# =========================

migration_done = cursor.execute("""
SELECT setting_value
FROM system_settings
WHERE setting_name = 'ist_migration'
""").fetchone()


if not migration_done:

    cursor.execute("""
    UPDATE files
    SET upload_time =
        datetime(upload_time, '+5 hours', '+30 minutes')
    """)

    cursor.execute("""
    UPDATE file_versions
    SET created_at =
        datetime(created_at, '+5 hours', '+30 minutes')
    """)

    cursor.execute("""
    UPDATE audit_logs
    SET log_time =
        datetime(log_time, '+5 hours', '+30 minutes')
    """)

    cursor.execute("""
    INSERT INTO system_settings
    (setting_name, setting_value)
    VALUES ('ist_migration', 'completed')
    """)


conn.commit()
conn.close()


print("Database and all tables created successfully!")
print("File sharing and user access tables are ready!")
print("Database migration completed safely!")