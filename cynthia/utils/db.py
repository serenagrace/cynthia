import sqlite3
from pathlib import Path


class Database:
    db_name = 'cynthia.db'

    def __init__(self, drive_path):
        if drive_path is None:
            print("Drive path is none. DB features disabled.")
        if not Path(drive_path).exists():
            print(f"Drive path {drive_path} does not exist. DB features disabled.")
        self.db_path = Path(drive_path) / self.db_name
        if not self.db_path.exists():
            self.create_db()

    def create_db(self):
        self.db_path.touch()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS config
                        (key TEXT PRIMARY KEY,
                         value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS uploads
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            filename TEXT,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            content TEXT,
                            version INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS servers
                            (name TEXT,
                            id TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            (name TEXT,
                            id TEXT PRIMARY KEY,
                            privileged INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                        (message_id TEXT PRIMARY KEY,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            server_id FOREIGN KEY REFERENCES servers(id),
                            user_id FOREIGN KEY REFERENCES users(id),
                            content TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS logs
                        (message_id TEXT FOREIGN KEY REFERENCES messages(message_id),
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            server_id FOREIGN KEY REFERENCES servers(id),
                            user_id FOREIGN KEY REFERENCES users(id),
                            content TEXT)''')
        conn.commit()
        conn.close()
