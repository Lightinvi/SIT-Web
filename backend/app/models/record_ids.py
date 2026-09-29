"""UUID record schemas and atomic migration of legacy IDs and their known references."""
import sqlite3
from uuid import uuid4


SCHEMAS = {
    'invitation_record': '''CREATE TABLE IF NOT EXISTS invitation_record (
        id TEXT PRIMARY KEY NOT NULL,
        requestId TEXT NOT NULL UNIQUE,
        visitorId TEXT NOT NULL,
        invitationCode TEXT NOT NULL,
        role TEXT NOT NULL,
        administratorId TEXT,
        administratorUsername TEXT,
        clickedAt REAL NOT NULL,
        eventType TEXT NOT NULL DEFAULT 'click' CHECK (eventType = 'click')
    )''',
    'daily_spinner': '''CREATE TABLE IF NOT EXISTS daily_spinner (
        id TEXT PRIMARY KEY NOT NULL,
        userId TEXT NOT NULL REFERENCES member(userId),
        spinDate TEXT NOT NULL,
        requestId TEXT NOT NULL,
        multiplier REAL NOT NULL CHECK(multiplier IN (0.5, 1, 2, 2.5, 5)),
        baseReward INTEGER NOT NULL CHECK(baseReward = 10),
        reward INTEGER NOT NULL CHECK(reward = baseReward * multiplier),
        createdAt REAL NOT NULL,
        UNIQUE(userId, spinDate), UNIQUE(userId, requestId)
    )''',
    'star_shard': '''CREATE TABLE IF NOT EXISTS star_shard (
        id TEXT PRIMARY KEY NOT NULL,
        sequence INTEGER NOT NULL UNIQUE CHECK(typeof(sequence) = 'integer' AND sequence > 0),
        userId TEXT NOT NULL REFERENCES member(userId),
        amount INTEGER NOT NULL CHECK(typeof(amount) = 'integer' AND amount != 0),
        beforeBlance INTEGER NOT NULL CHECK(typeof(beforeBlance) = 'integer' AND beforeBlance >= 0),
        afterBlance INTEGER NOT NULL CHECK(typeof(afterBlance) = 'integer' AND afterBlance BETWEEN 0 AND 9007199254740991),
        transactionType TEXT NOT NULL,
        transactionSource TEXT NOT NULL,
        description TEXT NOT NULL,
        createdAt REAL NOT NULL,
        CHECK(afterBlance = beforeBlance + amount)
    )''',
    'star_shard_request': '''CREATE TABLE IF NOT EXISTS star_shard_request (
        userId TEXT NOT NULL, requestId TEXT NOT NULL,
        recipientId TEXT NOT NULL, amount INTEGER NOT NULL,
        debitId TEXT NOT NULL REFERENCES star_shard(id),
        creditId TEXT NOT NULL REFERENCES star_shard(id),
        PRIMARY KEY(userId, requestId)
    )''',
}


def new_record_id():
    """Generate a UUID4, independent of table name, worker, and insertion order."""
    return str(uuid4())


def create_record_table(tx, table):
    """Create a known schema and restore its lookup index and immutability guards."""
    tx.execute(SCHEMAS[table])
    if table == 'star_shard':
        tx.execute('CREATE INDEX IF NOT EXISTS star_shard_user_latest ON star_shard(userId, sequence DESC)')
    if table in ('star_shard', 'daily_spinner'):
        for operation in ('UPDATE', 'DELETE'):
            tx.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
                BEFORE {operation} ON {table} BEGIN
                SELECT RAISE(ABORT, 'Business records are append-only'); END''')


def migrate_record_ids(tx):
    """Rebuild legacy record tables in the caller's immediate transaction.

    Migrate all related tables together so accessing any feature cannot leave
    ledger sources or transfer receipts pointing at old IDs. Preserve historical
    amounts, timestamps, and ledger insertion order, never sorting by UUID.
    Any unsupported references or integrity failure roll back the entire change.
    """
    existing = [table for table in SCHEMAS if tx.table_exists(table)]
    columns = {table: {row['name']: row['type'].upper() for row in tx.query(f'PRAGMA table_info({table})')}
               for table in existing}
    legacy = {table for table in existing if table != 'star_shard_request' and columns[table]['id'] != 'TEXT'}
    if not legacy:
        return
    for table in tx.list_tables():
        if table not in SCHEMAS:
            # Refuse unknown references rather than silently discarding future relations.
            for reference in tx.query('SELECT * FROM pragma_foreign_key_list(?)', (table,)):
                if reference['table'] in existing:
                    raise sqlite3.IntegrityError('Unsupported foreign key during record UUID migration')
    snapshots = {}
    mappings = {}
    for table in existing:
        order = 'sequence' if table == 'star_shard' and 'sequence' in columns[table] else 'rowid'
        snapshots[table] = tx.select(table, order_by=order)
        if table != 'star_shard_request':
            mappings[table] = {str(row['id']): new_record_id() if table in legacy else row['id']
                               for row in snapshots[table]}
    for table in ('star_shard_request', 'star_shard', 'daily_spinner', 'invitation_record'):
        if table in existing:
            tx.execute(f'DROP TABLE {table}')
    for table in existing:
        create_record_table(tx, table)
        for position, old in enumerate(snapshots[table], 1):
            row = dict(old)
            if table != 'star_shard_request':
                row['id'] = mappings[table][str(row['id'])]
            if table == 'invitation_record':
                for old_name, new_name in (
                    ('request_id', 'requestId'), ('visitor_id', 'visitorId'),
                    ('invitation_code', 'invitationCode'), ('administrator_id', 'administratorId'),
                    ('administrator_username', 'administratorUsername'),
                    ('clicked_at', 'clickedAt'), ('event_type', 'eventType'),
                ):
                    if old_name in row:
                        row[new_name] = row.pop(old_name)
            elif table == 'star_shard':
                row.setdefault('sequence', position)
                source_type = row['transactionType']
                if source_type in mappings:
                    source = str(row['transactionSource'])
                    if source not in mappings[source_type]:
                        raise sqlite3.IntegrityError('Unresolved ledger source during record UUID migration')
                    row['transactionSource'] = mappings[source_type][source]
            elif table == 'star_shard_request':
                for field in ('debitId', 'creditId'):
                    source = str(row[field])
                    if source not in mappings.get('star_shard', {}):
                        raise sqlite3.IntegrityError('Unresolved transfer receipt during record UUID migration')
                    row[field] = mappings['star_shard'][source]
            tx.insert(table, row)
    if tx.query('PRAGMA foreign_key_check'):
        raise sqlite3.IntegrityError('Foreign key violation during record UUID migration')
