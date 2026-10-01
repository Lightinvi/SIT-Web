"""Bounded read-only inspection of SQLite tables and rotating application logs."""
import fcntl
import json
from pathlib import Path

from itsdangerous import BadSignature, URLSafeSerializer

from app.sql.manager import identifier

PAGE_SIZE = 100


def table_page(db, table, sort=None, direction='asc', offset=0, search='', search_column=None):
    """Whitelist table/column identifiers and return one deterministic page."""
    if direction not in ('asc', 'desc') or offset < 0:
        raise ValueError('Invalid pagination')
    with db.transaction() as tx:
        if table not in tx.list_tables():
            raise ValueError('Unknown table')
        columns = tx.query(f'PRAGMA table_info({identifier(table)})')
        names = [column['name'] for column in columns]
        if search_column is not None and search_column not in names:
            raise ValueError('Unknown search column')
        search_names = [search_column] if search_column is not None else names
        if sort is not None and sort not in names:
            raise ValueError('Unknown column')
        primary = [column['name'] for column in sorted(columns, key=lambda c: c['pk']) if column['pk']]
        order = list(dict.fromkeys([sort or (primary or names)[0], *(primary or names)]))
        ordering = ', '.join(f'{identifier(name)} {direction.upper()}' for name in order)
        if len(search) > 500:
            raise ValueError('Search too long')
        condition = ''
        parameters = []
        if search:
            # Bound literal substring matching: %, _ and quotes are not SQL syntax.
            condition = ' WHERE ' + ' OR '.join(f'instr(lower(CAST({identifier(name)} AS TEXT)), lower(?)) > 0' for name in search_names)
            parameters = [search] * len(search_names)
        rows = tx.query(f'SELECT * FROM {identifier(table)}{condition} ORDER BY {ordering} LIMIT ? OFFSET ?', (*parameters, PAGE_SIZE + 1, offset))
    # JSON numbers cannot represent all SQLite integers without precision loss.
    rows = [{key: (str(value) if isinstance(value, int) and abs(value) > 9007199254740991
                   else value.hex() if isinstance(value, bytes) else value)
             for key, value in row.items()} for row in rows]
    return {'columns': names, 'rows': rows[:PAGE_SIZE],
            'nextOffset': offset + PAGE_SIZE if len(rows) > PAGE_SIZE else None}


def log_page(directory, secret, cursor=None):
    """Read a signed, byte-bounded snapshot newest first across both retained files.

    File inodes survive rotation; return an expired-snapshot error if a retained
    file is deleted. Never accept a client-provided file path.
    """
    directory = Path(directory)
    serializer = URLSafeSerializer(secret, salt='admin-log-page')
    try:
        snapshot = serializer.loads(cursor) if cursor else None
    except BadSignature:
        raise ValueError('Invalid cursor') from None
    if not directory.exists():
        return {'rows': [], 'nextCursor': None}
    with (directory / '.app.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        files = [path for path in (directory / 'app.log', directory / 'app.log.1') if path.exists()]
        available = {str(path.stat().st_ino): path for path in files}
        if snapshot is None:
            snapshot = {'files': [(str(path.stat().st_ino), path.stat().st_size) for path in files], 'offset': 0}
        rows = []
        for inode, size in snapshot['files']:
            if inode not in available or available[inode].stat().st_size < size:
                raise LookupError('Log snapshot expired')
            with available[inode].open('rb') as stream:
                lines = stream.read(min(size, 10 * 1024 * 1024)).splitlines()
            for line in reversed(lines):
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        rows.append({key: event.get(key) for key in (
                            'timestamp', 'level', 'requestId', 'message', 'route', 'method', 'status', 'durationMs')})
                except (ValueError, UnicodeDecodeError):
                    continue
    offset = snapshot['offset']
    page = rows[offset:offset + PAGE_SIZE]
    snapshot['offset'] += PAGE_SIZE
    return {'rows': page, 'nextCursor': serializer.dumps(snapshot) if len(rows) > offset + PAGE_SIZE else None}
