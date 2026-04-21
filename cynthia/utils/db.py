import sqlite3
from pathlib import Path
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

DB_PATH = "cynthia.db"


class Database:

    def __init__(self, drive):
        self.database_connected = False
        self.drive = drive
        if not self.drive.enabled:
            logger.warn(f"Drive not enabled. DB features disabled.")
            return
        self.db_path = self.drive.path(DB_PATH)
        if not self.drive.exists(DB_PATH, is_file=True):
            logger.info(
                f"Database file {self.db_path} does not exist. Creating new database."
            )
        self.create_db()
        self.database_connected = True

    def create_db(self):
        db_path = self.drive.touch(DB_PATH)
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS config
                        (key TEXT PRIMARY KEY,
                         value TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS uploads
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            filename TEXT,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            content TEXT,
                            version INT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS servers
                            (name TEXT,
                            id INTEGER PRIMARY KEY)""")
        c.execute("""CREATE TABLE IF NOT EXISTS users
                        (id INTEGER PRIMARY KEY,
                            name TEXT)""")
        c.execute(
            """CREATE TABLE IF NOT EXISTS channels
                            (name TEXT,
                            id INTEGER PRIMARY KEY,
                            server_id INTEGER,
                            CONSTRAINT server_id_fk FOREIGN KEY (server_id) REFERENCES servers(id))"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS messages
                        (id INTEGER PRIMARY KEY,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            server_id INT,
                            channel_id INT,
                            author INT,
                            jump_url TEXT,
                            content TEXT,
                            CONSTRAINT msg_server_fk FOREIGN KEY (server_id) REFERENCES servers(id),
                            CONSTRAINT msg_channel_fk FOREIGN KEY (channel_id) REFERENCES channels(id),
                            CONSTRAINT msg_author_fk FOREIGN KEY (author) REFERENCES users(id))"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS events
                        (event_type TEXT,
                            event_name TEXT,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            server_id INT,
                            channel_id INT,
                            user_id INT,
                            content TEXT,
                            CONSTRAINT event_server_fk FOREIGN KEY (server_id) REFERENCES servers(id),
                            CONSTRAINT event_channel_fk FOREIGN KEY (channel_id) REFERENCES channels(id),
                            CONSTRAINT event_user_fk FOREIGN KEY (user_id) REFERENCES users(id))"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS onmessage
                        (type TEXT,
                        server_id INT NULL,
                        channel_id INT NULL,
                        condition_type TEXT,
                        action_type TEXT,
                        CONSTRAINT onmessage_server_fk FOREIGN KEY (server_id) REFERENCES servers(id),
                        CONSTRAINT onmessage_channel_fk FOREIGN KEY (channel_id) REFERENCES channels(id))"""
        )
        conn.commit()
        conn.close()

    def insert_user(self, user, conn=None):
        close = False
        if not self.database_connected:
            return
        if conn is None:
            close = True
            conn = sqlite3.connect(self.drive.path(DB_PATH))
        c = conn.cursor()
        c.execute(
            """INSERT INTO users (id, name) VALUES (?, ?) on CONFLICT(id) DO UPDATE SET name=excluded.name""",
            (user.id, user.name),
        )
        if close:
            conn.commit()
            conn.close()

    def insert_server(self, server, conn=None):
        close = False
        if not self.database_connected:
            return
        if conn is None:
            close = True
            conn = sqlite3.connect(self.drive.path(DB_PATH))
        c = conn.cursor()
        c.execute(
            """INSERT INTO servers (id, name) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name""",
            (server.id, server.name),
        )
        if close:
            conn.commit()
            conn.close()

    def insert_channel(self, channel, guild, conn=None):
        close = False
        if not self.database_connected:
            return
        if conn is None:
            close = True
            conn = sqlite3.connect(self.drive.path(DB_PATH))
        self.insert_server(guild, conn)
        c = conn.cursor()
        c.execute(
            """INSERT INTO channels (id, name, server_id) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name""",
            (channel.id, channel.name, guild.id),
        )
        if close:
            conn.commit()
            conn.close()

    def insert_log(self, message):
        if not self.database_connected:
            return
        conn = sqlite3.connect(self.drive.path(DB_PATH))
        self.insert_channel(message.channel, message.guild, conn)
        self.insert_user(message.author, conn)
        c = conn.cursor()
        c.execute(
            """INSERT INTO messages (id, timestamp, server_id, channel_id, author, jump_url, content) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET jump_url = excluded.jump_url, content=excluded.content""",
            (
                message.id,
                message.created_at,
                message.guild.id,
                message.channel.id,
                message.author.id,
                message.jump_url,
                message.content,
            ),
        )
        conn.commit()
        conn.close()

    def clear_onmessage(self):
        if not self.database_connected:
            return
        conn = sqlite3.connect(self.drive.path(DB_PATH))
        c = conn.cursor()
        c.execute("""DELETE FROM onmessage""")
        conn.commit()
        conn.close()

    def insert_onmessage(self, onmessage):
        if not self.database_connected:
            return
        conn = sqlite3.connect(self.drive.path(DB_PATH))
        c = conn.cursor()
        self.insert_server(onmessage.guild, conn)
        self.insert_channel(onmessage.channel, onmessage.guild, conn)
        c.execute(
            """INSERT INTO onmessage (type, server_id, channel_id, condition_type, action_type) VALUES (?, ?, ?, ?, ?)""",
            (
                onmessage.type,
                onmessage.guild.id,
                onmessage.channel.id,
                onmessage.condition_type,
                onmessage.action_type,
            ),
        )
        conn.commit()
        conn.close()

    def get_onmessage(self, type=None, server_id=None, channel_id=None):
        if not self.database_connected:
            return []
        conn = sqlite3.connect(self.drive.path(DB_PATH))
        c = conn.cursor()
        query = "SELECT type, server_id, channel_id, condition_type, action_type FROM onmessage WHERE 1=1"
        params = []
        if type is not None:
            query += " AND type=?"
            params.append(type)
        if server_id is not None:
            query += " AND server_id=?"
            params.append(server_id)
        if channel_id is not None:
            query += " AND channel_id=?"
            params.append(channel_id)
        c.execute(query, params)
        results = c.fetchall()
        conn.close()
        return results
