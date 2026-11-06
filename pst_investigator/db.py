import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pst_files (
 id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
 size INTEGER NOT NULL DEFAULT 0, mtime REAL NOT NULL DEFAULT 0,
 sha256 TEXT, status TEXT NOT NULL DEFAULT 'discovered', total INTEGER NOT NULL DEFAULT 0,
 indexed INTEGER NOT NULL DEFAULT 0, errors TEXT, indexed_at TEXT
);
CREATE TABLE IF NOT EXISTS emails (
 id INTEGER PRIMARY KEY, pst_id INTEGER NOT NULL REFERENCES pst_files(id) ON DELETE CASCADE,
 folder TEXT, sender TEXT, to_recipients TEXT, cc TEXT, bcc TEXT, subject TEXT,
 sent_at TEXT, received_at TEXT, message_id TEXT, conversation TEXT, importance TEXT,
 size INTEGER DEFAULT 0, body_text TEXT, body_html TEXT, raw_eml BLOB,
 FOREIGN KEY(pst_id) REFERENCES pst_files(id)
);
CREATE TABLE IF NOT EXISTS attachments (
 id INTEGER PRIMARY KEY, email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
 filename TEXT, content_type TEXT, size INTEGER DEFAULT 0, data BLOB
);
CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
 subject, sender, to_recipients, cc, bcc, body_text, attachment_names,
 content=''
);
CREATE INDEX IF NOT EXISTS emails_pst_idx ON emails(pst_id);
CREATE INDEX IF NOT EXISTS emails_sent_idx ON emails(sent_at);
"""

def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn

def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

def get_setting(conn, key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default
