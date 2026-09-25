"""Persistent profiles of users who have passed Discord guild verification."""
from app.sql import SQLSession


def ensure_member_schema(tx: SQLSession) -> None:
    # Discord snowflakes remain strings, avoiding integer precision loss in clients.
    tx.execute('''CREATE TABLE IF NOT EXISTS member (
        user_id TEXT PRIMARY KEY NOT NULL,
        username TEXT,
        display_name TEXT,
        created_at REAL NOT NULL,
        last_login_at REAL NOT NULL
    )''')
    columns = {row['name'] for row in tx.query('PRAGMA table_info(member)')}
    for column in ('global_name', 'nickname', 'avatar_url', 'guild_joined_at'):
        if column not in columns:
            tx.execute(f'ALTER TABLE member ADD COLUMN {column} TEXT')


def record_login(tx: SQLSession, user: dict, logged_in_at: float) -> None:
    ensure_member_schema(tx)
    tx.execute('''INSERT INTO member
        (user_id, username, display_name, created_at, last_login_at,
         global_name, nickname, avatar_url, guild_joined_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            display_name = excluded.display_name,
            last_login_at = excluded.last_login_at,
            global_name = excluded.global_name,
            nickname = excluded.nickname,
            avatar_url = excluded.avatar_url,
            guild_joined_at = excluded.guild_joined_at
    ''', (user['id'], user.get('username'), user.get('name'), logged_in_at, logged_in_at,
          user.get('global_name'), user.get('nickname'), user.get('avatar_url'), user.get('guild_joined_at')))


def get_member(db, user_id):
    if not db.table_exists('member'):
        return None
    rows = db.select('member', {'user_id': user_id})
    if not rows:
        return None
    fields = ('user_id', 'username', 'display_name', 'created_at', 'last_login_at',
              'global_name', 'nickname', 'avatar_url', 'guild_joined_at')
    return {key: rows[0].get(key) for key in fields}
