"""Database-managed Discord invitations and immutable click-attribution records."""
import re
import time
from app.models.record_ids import create_record_table, migrate_record_ids, new_record_id

ROLES = ('訪客', '一般成員', '正規成員')
DEFAULT_INVITATIONS = (
    ('rnTHPNfjMx', ROLES[0], '我只是來看看的(登出或下線時將自動退出群組)'),
    ('HgtKZUX72K', ROLES[1], '成為長期活動成員(獲取基礎權限並且獲得網站功能使用權)'),
    ('UDNkUgQ4Yy', ROLES[2], '由管理員認證加入(需輸入由管理員派發的代碼)'),
)


class InvitationError(Exception):
    """Carry a public invitation error and its HTTP response status."""
    def __init__(self, message, status=400):
        """Associate the user-facing message with a validation or availability status."""
        super().__init__(message)
        self.status = status


def valid_code(code):
    """Accept only a Discord invite code, never a full URL or redirect target."""
    return isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_-]{2,100}', code) is not None


def ensure_schema(db):
    """Create invitation tables lazily and seed defaults only on initial creation.

    Existing settings, including deleted invitations, are never restored by a read.
    Legacy snake_case columns are renamed in place without removing click history.
    A write lock prevents competing first requests from seeding partial schemas.
    """
    with db.transaction(immediate=True) as tx:
        migrate_record_ids(tx)
        first_setup = not tx.table_exists('invitation_url')
        tx.execute('''CREATE TABLE IF NOT EXISTS invitation_url (
            code TEXT NOT NULL UNIQUE,
            role TEXT PRIMARY KEY NOT NULL,
            description TEXT NOT NULL,
            isExpired INTEGER NOT NULL DEFAULT 0 CHECK (isExpired IN (0, 1))
        )''')
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
        if first_setup:
            for code, role, description in DEFAULT_INVITATIONS:
                tx.insert('invitation_url', {'code': code, 'role': role,
                                             'description': description, 'isExpired': 0})


def get_invitation(db, role):
    """Return an available invitation or reject disabled, missing, or invalid settings."""
    rows = db.select('invitation_url', {'role': role})
    if not rows or rows[0]['isExpired'] or not valid_code(rows[0]['code']):
        raise InvitationError('此邀請暫時無法使用，請聯繫 discord/@lightinvi。', 410)
    return rows[0]


def record_click(db, role, visitor_id, request_id, administrator=None):
    """Record one click atomically and retain attribution snapshots after settings change.

    Retrying a request from the same browser reuses the record. Each genuinely new
    click uses another request ID. This does not assert Discord membership.
    """
    with db.transaction(immediate=True) as tx:
        invitation = get_invitation(tx, role)
        previous = tx.select('invitation_record', {'requestId': request_id})
        admin_id = administrator['id'] if administrator else None
        if previous:
            row = previous[0]
            if (row['visitorId'], row['role'], row['administratorId']) != (visitor_id, role, admin_id):
                raise InvitationError('請重新選擇邀請方式。', 409)
            if row['invitationCode'] != invitation['code']:
                raise InvitationError('邀請已更新，請重新選擇。', 409)
            return {'id': row['id'], 'code': row['invitationCode']}
        record_id = new_record_id()
        tx.insert('invitation_record', {
            'id': record_id,
            'requestId': request_id, 'visitorId': visitor_id,
            'invitationCode': invitation['code'], 'role': role,
            'administratorId': admin_id,
            'administratorUsername': administrator['username'] if administrator else None,
            'clickedAt': time.time(), 'eventType': 'click',
        })
        return {'id': record_id, 'code': invitation['code']}
