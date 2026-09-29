"""Persistent profiles of users who have passed Discord guild verification."""
from app.sql import SQLSession

PROFILE_COLUMNS = {
    'user_id': 'userId', 'username': 'username', 'display_name': 'displayName',
    'created_at': 'createdAt', 'last_login_at': 'lastLoginAt',
    'global_name': 'globalName', 'nickname': 'nickname',
    'avatar_url': 'avatarUrl', 'guild_joined_at': 'guildJoinedAt',
}


def ensure_member_schema(tx: SQLSession) -> None:
    """Rename legacy columns and add missing profile fields without deleting records."""
    # Discord snowflakes remain strings, avoiding integer precision loss in clients.
    tx.execute('''CREATE TABLE IF NOT EXISTS member (
        userId TEXT PRIMARY KEY NOT NULL,
        username TEXT,
        displayName TEXT,
        createdAt REAL NOT NULL,
        lastLoginAt REAL NOT NULL
    )''')
    columns = {row['name'] for row in tx.query('PRAGMA table_info(member)')}
    for old, new in PROFILE_COLUMNS.items():
        if old != new and old in columns:
            tx.execute(f'ALTER TABLE member RENAME COLUMN "{old}" TO "{new}"')
            columns.remove(old)
            columns.add(new)
    for column in ('globalName', 'nickname', 'avatarUrl', 'guildJoinedAt'):
        if column not in columns:
            tx.execute(f'ALTER TABLE member ADD COLUMN {column} TEXT')


def record_login(tx: SQLSession, user: dict, logged_in_at: float) -> None:
    """Upsert a verified Discord profile within the caller's transaction.

    Use the Discord ID as a text primary key and logged_in_at as Unix seconds.
    Refresh profile fields and last_login_at while preserving the first created_at.
    """
    ensure_member_schema(tx)
    tx.execute('''INSERT INTO member
        (userId, username, displayName, createdAt, lastLoginAt,
         globalName, nickname, avatarUrl, guildJoinedAt)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(userId) DO UPDATE SET
            username = excluded.username,
            displayName = excluded.displayName,
            lastLoginAt = excluded.lastLoginAt,
            globalName = excluded.globalName,
            nickname = excluded.nickname,
            avatarUrl = excluded.avatarUrl,
            guildJoinedAt = excluded.guildJoinedAt
    ''', (user['id'], user.get('username'), user.get('name'), logged_in_at, logged_in_at,
          user.get('global_name'), user.get('nickname'), user.get('avatar_url'), user.get('guild_joined_at')))


def get_member(db, user_id):
    """Migrate stored profiles and return the existing snake_case API representation."""
    with db.transaction(immediate=True) as tx:
        if not tx.table_exists('member'):
            return None
        ensure_member_schema(tx)
        rows = tx.select('member', {'userId': user_id})
    if not rows:
        return None
    return {key: rows[0].get(column) for key, column in PROFILE_COLUMNS.items()}
