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
        """Associate the user-facing message with a validation or availability status."""
        super().__init__(message)
        self.status = status


def valid_code(code):
    """Accept only a Discord invite code, never a full URL or redirect target."""
    return isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_-]{2,100}', code) is not None


def ensure_schema(db):
    """Migrate click history and remove the obsolete static invitation table."""
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


def record_click(db, role, visitor_id, request_id, administrator=None, *, discord=None):
    """Reuse the visitor's unexpired invitation for the selected role before creating another one.

    Keep the original role, attribution, and creation time when reusing a link.
    Serialize lookup and generation across workers, including different request IDs.
    """
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
