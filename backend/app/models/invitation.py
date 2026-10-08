"""Dynamic Discord invitations and immutable click-attribution records."""
import re
import time
from app.models.record_ids import create_record_table, migrate_record_ids, new_record_id

ROLES = ('訪客', '一般成員', '正規成員')
INVITATIONS = {
    ROLES[0]: dict(channel_id='1554311970226704444', role_ids=[], temporary=True,
                  description='我只是來看看的(登出或下線時將自動退出群組)'),
    ROLES[1]: dict(channel_id='751099765940289596', role_ids=['578156037589172244'], temporary=False,
                  description='成為長期活動成員(獲取基礎權限並且獲得網站功能使用權)'),
    ROLES[2]: dict(channel_id='578156795667808276', role_ids=['749803225275695156'], temporary=False,
                  description='由管理員認證加入(需輸入由管理員派發的代碼)'),
}
INVITE_MAX_AGE = 600


class InvitationError(Exception):
    """Carry a public invitation error and its HTTP response status."""
    def __init__(self, message, status=400):
        """Associate the user-facing message with a validation or availability status.
        設定可公開的邀請錯誤訊息與 HTTP 狀態。

        Args:
            message: 可公開的錯誤訊息。
            status: HTTP 回應狀態碼。 預設為 400。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> result = InvitationError(message=message)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        super().__init__(message)
        self.status = status


def valid_code(code):
    """Accept only a Discord invite code, never a full URL or redirect target.
    檢查 Discord 邀請代碼的字元與長度。

    Args:
        code: Discord 邀請網址最後一段的邀請代碼。

    Returns:
        bool: 代碼格式是否有效。

    Example:
        >>> result = valid_code(code=code)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_-]{2,100}', code) is not None


def ensure_schema(db):
    """Migrate click history and remove the obsolete static invitation table.
    初始化或遷移邀請點擊紀錄，並移除舊靜態邀請表及必要索引與約束。

    Args:
        db: 提供 transaction 方法的 SQLManager。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> result = ensure_schema(db=db)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return InvitationService(db).ensure_schema()


def record_click(db, role, visitor_id, request_id, administrator=None, *, discord=None):
    """Reuse the visitor's unexpired invitation for the selected role before creating another one.

    Keep the original role, attribution, and creation time when reusing a link.
    Serialize lookup and generation across workers, including different request IDs.
    優先重用同訪客同身份的有效邀請，必要時建立新邀請並儲存點擊與推薦人紀錄。

    Args:
        db: 提供 transaction 方法的 SQLManager。
        role: 選取的加入身份名稱，須為 ROLES 內的選項。
        visitor_id: 儲存於 Flask session 的匿名訪客識別碼。
        request_id: 此操作的冪等識別碼；重試時須沿用相同值。
        administrator: 已驗證推薦人的 id 與 username 對照表，或 None。 預設為 None。
        discord: 用於動態建立邀請的 DiscordService。 預設為 None。

    Returns:
        dict: 含 id 與 code 的新建或重用邀請。

    Exceptions:
        InvitationError: 邀請方式、歸屬、期限或服务設定不符合要求。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = record_click(db=db, role=role, visitor_id="example-visitor", request_id="00000000-0000-4000-8000-000000000001")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return InvitationService(db).record_click(role, visitor_id, request_id, administrator, discord=discord)


class InvitationService:
    """Own invitation history and retry-safe Discord link issuance.
    管理邀請歷史與可安全重試的 Discord 邀請發行。
    """

    def __init__(self, db):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            db: 此服務所使用的 SQLManager；各寫入方法自行管理原子交易。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = InvitationService(db)
            相依項目須先依 Args 建立。
        """
        self.db = db

    def ensure_schema(self):
        """Migrate click history and remove the obsolete static invitation table.
        初始化或遷移邀請點擊紀錄，並移除舊靜態邀請表及必要索引與約束。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> service = InvitationService(db)
            >>> result = service.ensure_schema()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
        with db.transaction(immediate=True) as tx:
            migrate_record_ids(tx)
            create_record_table(tx, 'invitation_record')
            columns = {column['name'] for column in tx.query('PRAGMA table_info(invitation_record)')}
            for old, new in (
                ('request_id', 'requestId'), ('visitor_id', 'visitorId'),
                ('invitation_code', 'invitationCode'), ('administrator_id', 'administratorId'),
                ('administrator_username', 'administratorUsername'),
                ('clicked_at', 'clickedAt'), ('event_type', 'eventType'),
            ):
                if old in columns:
                    tx.execute(f'ALTER TABLE invitation_record RENAME COLUMN "{old}" TO "{new}"')
            tx.execute('DROP TABLE IF EXISTS invitation_url')
            tx.execute('DROP INDEX IF EXISTS invitation_record_visitor_latest')
            tx.execute('CREATE INDEX IF NOT EXISTS invitation_record_visitor_role_latest '
                       'ON invitation_record(visitorId, role, clickedAt DESC)')

    def record_click(self, role, visitor_id, request_id, administrator=None, *, discord=None):
        """Reuse the visitor's unexpired invitation for the selected role before creating another one.

        Keep the original role, attribution, and creation time when reusing a link.
        Serialize lookup and generation across workers, including different request IDs.
        優先重用同訪客同身份的有效邀請，必要時建立新邀請並儲存點擊與推薦人紀錄。

        Args:
            role: 選取的加入身份名稱，須為 ROLES 內的選項。
            visitor_id: 儲存於 Flask session 的匿名訪客識別碼。
            request_id: 此操作的冪等識別碼；重試時須沿用相同值。
            administrator: 已驗證推薦人的 id 與 username 對照表，或 None。 預設為 None。
            discord: 用於動態建立邀請的 DiscordService。 預設為 None。

        Returns:
            dict: 含 id 與 code 的新建或重用邀請。

        Exceptions:
            InvitationError: 邀請方式、歸屬、期限或服务設定不符合要求。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> service = InvitationService(db)
            >>> result = service.record_click(role=role, visitor_id=visitor_id, request_id=request_id)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
        with db.transaction(immediate=True) as tx:
            previous = tx.select('invitation_record', {'requestId': request_id})
            admin_id = administrator['id'] if administrator else None
            if previous:
                row = previous[0]
                if (row['visitorId'], row['role'], row['administratorId']) != (visitor_id, role, admin_id):
                    raise InvitationError('請重新選擇邀請方式。', 409)
                if time.time() >= row['clickedAt'] + INVITE_MAX_AGE:
                    raise InvitationError('邀請已過期，請關閉視窗後重新取得邀請。', 410)
                return {'id': row['id'], 'code': row['invitationCode']}
            active = tx.query(
                'SELECT * FROM invitation_record WHERE visitorId = ? AND role = ? AND clickedAt > ? '
                'ORDER BY clickedAt DESC, rowid DESC LIMIT 1',
                (visitor_id, role, time.time() - INVITE_MAX_AGE),
            )
            if active:
                row = active[0]
                return {'id': row['id'], 'code': row['invitationCode']}
            if role not in INVITATIONS:
                raise InvitationError('請選擇有效的加入方式。')
            if discord is None:
                raise InvitationError('邀請服務尚未設定完成。', 503)
            created_at = time.time()
            code = discord.create_invite(**{key: value for key, value in INVITATIONS[role].items() if key != 'description'})
            record_id = new_record_id()
            tx.insert('invitation_record', {
                'id': record_id,
                'requestId': request_id, 'visitorId': visitor_id,
                'invitationCode': code, 'role': role,
                'administratorId': admin_id,
                'administratorUsername': administrator['username'] if administrator else None,
                'clickedAt': created_at, 'eventType': 'click',
            })
            return {'id': record_id, 'code': code}
