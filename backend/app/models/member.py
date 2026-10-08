"""Persistent profiles of users who have passed Discord guild verification."""
import json

from app.sql import SQLSession

PROFILE_COLUMNS = {
    'user_id': 'userId', 'username': 'username', 'display_name': 'displayName',
    'created_at': 'createdAt', 'last_login_at': 'lastLoginAt',
    'global_name': 'globalName', 'nickname': 'nickname',
    'avatar_url': 'avatarUrl', 'guild_joined_at': 'guildJoinedAt',
}


def ensure_member_schema(tx: SQLSession) -> None:
    """Rename legacy columns and add missing profile fields without deleting records.
    遷移舊欄位並補齊成員資料與權限欄位，保留既有紀錄。

    Args:
        tx (SQLSession): 目前交易的 SQLSession；由呼叫者管理提交與回滾。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = ensure_member_schema(tx=tx)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    # Discord snowflakes remain strings, avoiding integer precision loss in clients.
    return MemberProfileStore(tx).ensure_member_schema()


def record_login(tx: SQLSession, user: dict, logged_in_at: float) -> None:
    """Upsert a verified Discord profile within the caller's transaction.

    Use the Discord ID as a text primary key and logged_in_at as Unix seconds.
    Refresh profile fields and last_login_at while preserving the first created_at.
    在呼叫者交易內新增或更新驗證過的成員資料，保留首次建立時間。

    Args:
        tx (SQLSession): 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        user (dict): 已驗證用戶的資料對照表。
        logged_in_at (float): 此次登入的 Unix 秒數。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = record_login(tx=tx, user=user, logged_in_at=logged_in_at)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return MemberProfileStore(tx).record_login(user, logged_in_at)


def get_member(db, user_id):
    """Migrate stored profiles and return the existing snake_case API representation.
    遷移必要欄位後讀取指定成員，回傳 snake_case API 資料。

    Args:
        db: 提供 transaction 方法的 SQLManager。
        user_id: Discord 使用者 ID 字串。

    Returns:
        dict | None: 成員 API 資料，找不到時為 None。

    Example:
        >>> result = get_member(db=db, user_id="123456789012345678")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return MemberRepository(db).get_member(user_id)


class MemberProfileStore:
    """Persist verified member profiles within one caller-owned transaction.
    在呼叫者交易內管理成員結構與已驗證的登入資料。
    """

    def __init__(self, tx):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            tx: 目前交易的 SQLSession，物件不得超出該交易生命週期。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = MemberProfileStore(tx)
            相依項目須先依 Args 建立。
        """
        self.tx = tx

    def ensure_member_schema(self):
        """Rename legacy columns and add missing profile fields without deleting records.
        遷移舊欄位並補齊成員資料與權限欄位，保留既有紀錄。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = MemberProfileStore(tx)
            ...     result = service.ensure_member_schema()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
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
        if 'roleIds' not in columns:
            tx.execute('ALTER TABLE member ADD COLUMN roleIds TEXT')
        if 'rolesUpdatedAt' not in columns:
            tx.execute('ALTER TABLE member ADD COLUMN rolesUpdatedAt REAL')

    def record_login(self, user: dict, logged_in_at: float):
        """Upsert a verified Discord profile within the caller's transaction.

        Use the Discord ID as a text primary key and logged_in_at as Unix seconds.
        Refresh profile fields and last_login_at while preserving the first created_at.
        在呼叫者交易內新增或更新驗證過的成員資料，保留首次建立時間。

        Args:
            user (dict): 已驗證用戶的資料對照表。
            logged_in_at (float): 此次登入的 Unix 秒數。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = MemberProfileStore(tx)
            ...     result = service.record_login(user=user, logged_in_at=logged_in_at)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        self.ensure_member_schema()
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
        tx.update('member', {'roleIds': json.dumps(user.get('role_ids', [])),
                             'rolesUpdatedAt': logged_in_at}, {'userId': user['id']})


class MemberRepository:
    """Read authoritative member profiles through an injected database.
    透過注入的資料庫查詢權威成員資料。
    """

    def __init__(self, db):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            db: 此服務所使用的 SQLManager；各寫入方法自行管理原子交易。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = MemberRepository(db)
            相依項目須先依 Args 建立。
        """
        self.db = db

    def get_member(self, user_id):
        """Migrate stored profiles and return the existing snake_case API representation.
        遷移必要欄位後讀取指定成員，回傳 snake_case API 資料。

        Args:
            user_id: Discord 使用者 ID 字串。

        Returns:
            dict | None: 成員 API 資料，找不到時為 None。

        Example:
            >>> service = MemberRepository(db)
            >>> result = service.get_member(user_id=user_id)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
        with db.transaction(immediate=True) as tx:
            if not tx.table_exists('member'):
                return None
            MemberProfileStore(tx).ensure_member_schema()
            rows = tx.select('member', {'userId': user_id})
        if not rows:
            return None
        return {**{key: rows[0].get(column) for key, column in PROFILE_COLUMNS.items()},
                'role_ids': json.loads(rows[0]['roleIds']) if rows[0]['roleIds'] else [],
                'roles_updated_at': rows[0]['rolesUpdatedAt']}
