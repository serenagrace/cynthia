"""SQLite persistence for message logs, on-message rules, and Twitch chat memory."""

import contextlib
import logging
import sqlite3
import time

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

DB_PATH = "cynthia.db"


class Database:
    """Store Discord entities, message logs, and on-message rules in SQLite."""

    def __init__(self, drive):
        """Connect to the drive-backed database when drive storage is available."""
        self.database_connected = False
        self.drive = drive
        if not self.drive.enabled:
            logger.warning("Drive not enabled. DB features disabled.")
            return
        self.db_path = self.drive.path(DB_PATH)
        if not self.drive.exists(DB_PATH, is_file=True):
            logger.notice(
                f"Database file {self.db_path} does not exist. Creating new database."
            )
        self.create_db()
        self.database_connected = True

    def create_db(self):
        """Create the database tables when they do not already exist."""
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
                        CONSTRAINT onmessage_channel_fk FOREIGN KEY (channel_id) REFERENCES channels(id),
                        UNIQUE (type, server_id, channel_id, condition_type, action_type))"""
        )
        # Twitch chat history; flagged holds the moderation reason, if any
        c.execute("""CREATE TABLE IF NOT EXISTS twitch_chat
                        (id TEXT PRIMARY KEY,
                         time REAL,
                         login TEXT,
                         user_id TEXT,
                         display TEXT,
                         text TEXT,
                         flagged TEXT NULL,
                         deleted INT DEFAULT 0)""")
        c.execute(
            "CREATE INDEX IF NOT EXISTS twitch_chat_login ON twitch_chat (login, time)"
        )
        # What the chat model remembers about each chatter
        c.execute("""CREATE TABLE IF NOT EXISTS chatter_memory
                        (login TEXT PRIMARY KEY,
                         display TEXT,
                         notes TEXT DEFAULT '',
                         message_count INT DEFAULT 0,
                         streams INT DEFAULT 0,
                         first_seen REAL,
                         last_seen REAL,
                         learned_until REAL DEFAULT 0,
                         updated_at REAL,
                         kind_count INT DEFAULT 0,
                         rude_count INT DEFAULT 0)""")
        columns = {row[1] for row in c.execute("PRAGMA table_info(chatter_memory)")}
        for column in ("kind_count", "rude_count"):
            if column not in columns:
                c.execute(
                    f"ALTER TABLE chatter_memory ADD COLUMN {column} INT DEFAULT 0"
                )
        # Messages showing a chatter's pronouns: their own statement or how
        # someone else (by_login) referred to them
        c.execute("""CREATE TABLE IF NOT EXISTS chatter_pronouns
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         login TEXT,
                         pronouns TEXT,
                         kind TEXT,
                         by_login TEXT,
                         text TEXT,
                         time REAL)""")
        c.execute(
            "CREATE INDEX IF NOT EXISTS chatter_pronouns_login "
            "ON chatter_pronouns (login, time)"
        )
        # Words chat uses for a chatter (by fuzzy match), and how often
        c.execute("""CREATE TABLE IF NOT EXISTS chatter_nicknames
                        (login TEXT,
                         nickname TEXT,
                         uses INT DEFAULT 0,
                         first_seen REAL,
                         last_seen REAL,
                         PRIMARY KEY (login, nickname))""")
        # Facts one chatter (by_login) stated about another, with their words
        c.execute("""CREATE TABLE IF NOT EXISTS chatter_hearsay
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         login TEXT,
                         fact TEXT,
                         by_login TEXT,
                         quote TEXT,
                         time REAL)""")
        # What the owner taught the chat model, and their conversation with it
        c.execute("""CREATE TABLE IF NOT EXISTS llm_lessons
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         section TEXT,
                         text TEXT,
                         created_at REAL,
                         updated_at REAL)""")
        # Things the chat model tried to say that moderation blocked
        c.execute("""CREATE TABLE IF NOT EXISTS llm_filtered
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         time REAL,
                         kind TEXT,
                         reason TEXT,
                         text TEXT,
                         trigger TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS llm_owner_chat
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         time REAL,
                         role TEXT,
                         text TEXT)""")
        conn.commit()
        conn.close()

    def insert_user(self, user, conn=None):
        """Insert or update a user record using an optional open connection."""
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
        """Insert or update a server record using an optional open connection."""
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
        """Insert or update a channel and its server record."""
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
        """Persist a Discord message and its related server, channel, and user."""
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
        """Delete all persisted on-message rules."""
        if not self.database_connected:
            return
        conn = sqlite3.connect(self.drive.path(DB_PATH))
        c = conn.cursor()
        c.execute("""DELETE FROM onmessage""")
        conn.commit()
        conn.close()

    def insert_onmessage(self, onmessage):
        """Persist an on-message rule unless an identical rule already exists."""
        if not self.database_connected:
            return
        conn = sqlite3.connect(self.drive.path(DB_PATH))
        c = conn.cursor()
        self.insert_server(onmessage.guild, conn)
        self.insert_channel(onmessage.channel, onmessage.guild, conn)
        c.execute(
            """INSERT OR IGNORE INTO onmessage (type, server_id, channel_id, condition_type, action_type) VALUES (?, ?, ?, ?, ?)""",
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

    def get_onmessage(self, _type=None, server_id=None, channel_id=None):
        """Return persisted rules matching the supplied optional filters."""
        if not self.database_connected:
            return []
        conn = sqlite3.connect(self.drive.path(DB_PATH))
        c = conn.cursor()
        query = "SELECT type, server_id, channel_id, condition_type, action_type FROM onmessage WHERE 1=1"
        params = []
        if _type is not None:
            query += " AND type=?"
            params.append(_type)
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

    @contextlib.contextmanager
    def _connect(self):
        """Open a committed connection whose rows read like dicts."""
        conn = sqlite3.connect(self.drive.path(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_chat_message(self, message, stream_start=None):
        """Store a Twitch chat message and update its chatter's counters.

        `message` has `id`, `time`, `login`, `user_id`, `user` and `text`, plus
        `flagged` (the moderation reason or None). A chatter's stream count
        goes up with their first message after `stream_start`.
        """
        if not self.database_connected:
            return
        login = message["login"]
        at = message["time"]
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO twitch_chat
                   (id, time, login, user_id, display, text, flagged)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    message.get("id") or f"{login}:{at}",
                    at,
                    login,
                    message.get("user_id"),
                    message.get("user") or login,
                    message["text"],
                    message.get("flagged"),
                ),
            )
            row = conn.execute(
                "SELECT last_seen FROM chatter_memory WHERE login=?", (login,)
            ).fetchone()
            new_stream = int(
                row is None
                or stream_start is None
                or (row["last_seen"] or 0) < stream_start
            )
            conn.execute(
                """INSERT INTO chatter_memory
                   (login, display, message_count, streams, first_seen, last_seen)
                   VALUES (?, ?, 1, 1, ?, ?)
                   ON CONFLICT(login) DO UPDATE SET
                     display=excluded.display,
                     message_count=message_count + 1,
                     streams=streams + ?,
                     last_seen=excluded.last_seen""",
                (login, message.get("user") or login, at, at, new_stream),
            )

    def count_tone(self, login, tone):
        """Count one kind or rude message `login` aimed at the bot."""
        if not self.database_connected or tone not in ("kind", "rude"):
            return
        with self._connect() as conn:
            conn.execute(
                f"UPDATE chatter_memory SET {tone}_count = {tone}_count + 1 "
                "WHERE login=?",
                (login.lower(),),
            )

    def delete_chat_messages(self, message_id=None, login=None, user_id=None):
        """Mark messages a moderator removed: one by ID, or all of one chatter's."""
        if not self.database_connected:
            return
        with self._connect() as conn:
            if message_id is not None:
                conn.execute(
                    "UPDATE twitch_chat SET deleted=1 WHERE id=?", (message_id,)
                )
            elif user_id:
                conn.execute(
                    "UPDATE twitch_chat SET deleted=1 WHERE user_id=?", (user_id,)
                )
            elif login:
                conn.execute("UPDATE twitch_chat SET deleted=1 WHERE login=?", (login,))

    def chat_messages(self, login, since=0, limit=10):
        """A chatter's clean messages after `since`, oldest first, newest `limit`."""
        if not self.database_connected:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, time, login, display AS user, text FROM twitch_chat
                   WHERE login=? AND time>? AND flagged IS NULL AND deleted=0
                   ORDER BY time DESC LIMIT ?""",
                (login, since, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def chatter(self, login):
        """A chatter's memory row as a dict, or None if they've never chatted."""
        rows = self.chatters([login])
        return rows[0] if rows else None

    def chatters(self, logins):
        """Memory rows for the given logins, in the order given."""
        if not self.database_connected or not logins:
            return []
        logins = [login.lower() for login in logins]
        marks = ",".join("?" * len(logins))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM chatter_memory WHERE login IN ({marks})", logins
            ).fetchall()
            nicknames = conn.execute(
                f"""SELECT login, nickname, uses FROM chatter_nicknames
                    WHERE login IN ({marks}) ORDER BY uses DESC""",
                logins,
            ).fetchall()
            hearsay = conn.execute(
                f"""SELECT login, fact, by_login, quote, time FROM chatter_hearsay
                    WHERE login IN ({marks}) ORDER BY time""",
                logins,
            ).fetchall()
            evidence = conn.execute(
                f"""SELECT login, pronouns, kind, by_login, text, time
                    FROM chatter_pronouns WHERE login IN ({marks})
                    ORDER BY time""",
                logins,
            ).fetchall()
        found = {
            row["login"]: dict(row, pronoun_evidence=[], nicknames=[], hearsay=[])
            for row in rows
        }
        for key, extra in (
            ("pronoun_evidence", evidence),
            ("nicknames", nicknames),
            ("hearsay", hearsay),
        ):
            for row in extra:
                if row["login"] in found:
                    found[row["login"]][key].append(dict(row))
        return [found[login] for login in logins if login in found]

    def add_nickname_use(self, login, nickname, at=None):
        """Count one use of `nickname` for `login`; returns its use count."""
        if not self.database_connected:
            return 0
        at = at or time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO chatter_nicknames
                   (login, nickname, uses, first_seen, last_seen)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(login, nickname) DO UPDATE SET
                     uses=uses + 1, last_seen=excluded.last_seen""",
                (login.lower(), nickname.lower(), at, at),
            )
            row = conn.execute(
                "SELECT uses FROM chatter_nicknames WHERE login=? AND nickname=?",
                (login.lower(), nickname.lower()),
            ).fetchone()
        return row["uses"]

    def add_hearsay(self, login, fact, by_login, quote, at=None):
        """Keep a fact `by_login` stated about `login`, with their words."""
        if not self.database_connected:
            return
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO chatter_hearsay (login, fact, by_login, quote, time)
                   VALUES (?, ?, ?, ?, ?)""",
                (login.lower(), fact, by_login.lower(), quote, at or time.time()),
            )

    def resolve_chatter(self, name, min_uses=3):
        """The login for a login, display name or common nickname, or None."""
        name = name.strip().lstrip("@").lower()
        return self.chatter_names(min_uses).get(name) if name else None

    def add_pronoun_evidence(self, login, pronouns, kind, by_login, text, at=None):
        """Keep a message showing `login`'s pronouns (`kind` self or reference)."""
        if not self.database_connected:
            return
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO chatter_pronouns
                   (login, pronouns, kind, by_login, text, time)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    login.lower(),
                    pronouns,
                    kind,
                    by_login.lower(),
                    text,
                    at or time.time(),
                ),
            )

    def chatter_names(self, min_uses=3):
        """Every known chatter as `{lowercase login, display name or nickname: login}`.

        Nicknames count once used `min_uses` times, and only when they belong
        to one chatter and aren't someone else's login or display name.
        """
        if not self.database_connected:
            return {}
        with self._connect() as conn:
            rows = conn.execute("SELECT login, display FROM chatter_memory").fetchall()
            nicknames = conn.execute(
                "SELECT nickname, login FROM chatter_nicknames WHERE uses >= ?",
                (min_uses,),
            ).fetchall()
        names = {}
        for row in rows:
            names[row["login"]] = row["login"]
            if row["display"]:
                names.setdefault(row["display"].lower(), row["login"])
        owners = {}
        for row in nicknames:
            owners.setdefault(row["nickname"], set()).add(row["login"])
        for nickname, logins in owners.items():
            if len(logins) == 1:
                names.setdefault(nickname, next(iter(logins)))
        return names

    def chatters_to_learn(self, batch, idle_before, limit=5):
        """Chatters with unlearned messages: at least `batch`, or any once idle.

        Idle means their last message is older than `idle_before`. Returns
        `(login, pending count)` pairs, the most pending first.
        """
        if not self.database_connected:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT m.login, COUNT(c.id) AS pending, m.last_seen
                   FROM chatter_memory m JOIN twitch_chat c
                     ON c.login = m.login AND c.time > m.learned_until
                    AND c.flagged IS NULL AND c.deleted = 0
                   GROUP BY m.login
                   HAVING pending >= ? OR m.last_seen < ?
                   ORDER BY pending DESC LIMIT ?""",
                (batch, idle_before, limit),
            ).fetchall()
        return [(row["login"], row["pending"]) for row in rows]

    def set_chatter_notes(self, login, notes, learned_until=None):
        """Replace a chatter's notes; `learned_until` marks the messages used."""
        if not self.database_connected:
            return
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO chatter_memory (login, display, notes, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(login) DO UPDATE SET notes=excluded.notes,
                     updated_at=excluded.updated_at""",
                (login, login, notes, time.time()),
            )
            if learned_until is not None:
                conn.execute(
                    "UPDATE chatter_memory SET learned_until=? WHERE login=?",
                    (learned_until, login),
                )

    def forget_chatter(self, login):
        """Delete a chatter's memory and stored messages; True if anything existed."""
        if not self.database_connected:
            return False
        with self._connect() as conn:
            gone = conn.execute(
                "DELETE FROM chatter_memory WHERE login=?", (login,)
            ).rowcount
            gone += conn.execute(
                "DELETE FROM twitch_chat WHERE login=?", (login,)
            ).rowcount
            for table in ("chatter_pronouns", "chatter_hearsay"):
                gone += conn.execute(
                    f"DELETE FROM {table} WHERE login=? OR by_login=?",
                    (login, login),
                ).rowcount
            gone += conn.execute(
                "DELETE FROM chatter_nicknames WHERE login=?", (login,)
            ).rowcount
        return bool(gone)

    def lessons(self):
        """Everything the owner taught the chat model, oldest first."""
        if not self.database_connected:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, section, text, updated_at FROM llm_lessons ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_lesson(self, section, text):
        """Store a new lesson; returns its ID."""
        if not self.database_connected:
            return None
        now = time.time()
        with self._connect() as conn:
            return conn.execute(
                """INSERT INTO llm_lessons (section, text, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (section, text, now, now),
            ).lastrowid

    def update_lesson(self, lesson_id, text, section=None):
        """Rewrite a lesson; True if it existed."""
        if not self.database_connected:
            return False
        with self._connect() as conn:
            return bool(
                conn.execute(
                    """UPDATE llm_lessons SET text=?, section=COALESCE(?, section),
                       updated_at=? WHERE id=?""",
                    (text, section, time.time(), lesson_id),
                ).rowcount
            )

    def remove_lesson(self, lesson_id):
        """Delete a lesson; True if it existed."""
        if not self.database_connected:
            return False
        with self._connect() as conn:
            return bool(
                conn.execute(
                    "DELETE FROM llm_lessons WHERE id=?", (lesson_id,)
                ).rowcount
            )

    def add_owner_chat(self, role, text):
        """Store one turn of the owner's conversation with the chat model."""
        if not self.database_connected:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO llm_owner_chat (time, role, text) VALUES (?, ?, ?)",
                (time.time(), role, text),
            )

    def owner_chat(self, limit=12):
        """The newest `limit` turns of the owner's conversation, oldest first."""
        if not self.database_connected:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT time, role, text FROM llm_owner_chat ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear_owner_chat(self):
        """Forget the owner's conversation (lessons stay)."""
        if not self.database_connected:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM llm_owner_chat")

    def list_chatters(self, search="", limit=20, offset=0):
        """Chatters whose login, name or notes contain `search`, newest first.

        Returns `(rows, total)`.
        """
        if not self.database_connected:
            return [], 0
        like = f"%{search.lower()}%"
        where = (
            "WHERE lower(login) LIKE ? OR lower(display) LIKE ? OR lower(notes) LIKE ? "
            "OR login IN (SELECT login FROM chatter_nicknames "
            "WHERE nickname LIKE ? AND uses >= 3)"
        )
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM chatter_memory {where}", (like,) * 4
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT * FROM chatter_memory {where}
                    ORDER BY last_seen DESC LIMIT ? OFFSET ?""",
                (*(like,) * 4, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows], total

    def add_filtered(self, kind, reason, text, trigger=""):
        """Log a blocked model output; returns its ID."""
        if not self.database_connected:
            return None
        with self._connect() as conn:
            return conn.execute(
                """INSERT INTO llm_filtered (time, kind, reason, text, trigger)
                   VALUES (?, ?, ?, ?, ?)""",
                (time.time(), kind, reason, text, trigger),
            ).lastrowid

    def filtered(self, since=0, limit=20):
        """Blocked model outputs after `since`, newest first."""
        if not self.database_connected:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM llm_filtered WHERE time>?
                   ORDER BY id DESC LIMIT ?""",
                (since, limit),
            ).fetchall()
        return [dict(row) for row in rows]
