"""Bounded read-only inspection of SQLite tables and rotating application logs."""
import fcntl
import json
from pathlib import Path

from itsdangerous import BadSignature, URLSafeSerializer

from app.sql.manager import identifier

PAGE_SIZE = 100


def table_page(db, table, sort=None, direction='asc', offset=0, search='', search_column=None):
    """Whitelist table/column identifiers and return one deterministic page.
    驗證表名與欄位，先搜尋及排序，再回傳最多一百筆資料。

    Args:
        db: 提供 transaction 方法的 SQLManager。
        table: 資料表名稱。
        sort: 排序欄位，或 None 使用預設順序。 預設為 None。
        direction: 排序方向，限 asc 或 desc。 預設為 'asc'。
        offset: 略過的資料筆數，須為非負整數。 預設為 0。
        search: 以字面子字串比對的搜尋內容。 預設為 ''。
        search_column: 指定搜尋欄位，或 None 搜尋全部欄位。 預設為 None。

    Returns:
        dict: columns、最多一百筆 rows 及 nextOffset。

    Exceptions:
        ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = table_page(db=db, table="member")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return DatabaseReader(db).table_page(table, sort, direction, offset, search, search_column)


def log_page(directory, secret, cursor=None):
    """Read a signed, byte-bounded snapshot newest first across both retained files.

    File inodes survive rotation; return an expired-snapshot error if a retained
    file is deleted. Never accept a client-provided file path.
    依簽章游標讀取兩份保留日誌的最新快照，檔案失效時要求重新載入。

    Args:
        directory: 日誌儲存目錄。
        secret: 用於游標簽章的伺服器密鑰。
        cursor: 上一頁回傳的簽章游標，首次讀取使用 None。 預設為 None。

    Returns:
        dict: 日誌 rows 與簽章 nextCursor。

    Exceptions:
        ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
        LookupError: 日誌快照對應檔案已刪除或縮小，須重新載入。 若由下列處理流程捕捉，則依其轉換規則處理。
        BadSignature: 捕捉後轉換為上列業務或驗證例外。
        ValueError, UnicodeDecodeError: 已在函式內捕捉，使用備援流程、略過無效資料或完成清理。

    Example:
        >>> result = log_page(directory=directory, secret=secret)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return LogReader(directory, secret).log_page(cursor)


class DatabaseReader:
    """Inspect database pages through an injected read dependency.
    透過資料庫相依項目提供有界的搜尋與分頁查閱。
    """

    def __init__(self, db):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            db: 此服務所使用的 SQLManager；各寫入方法自行管理原子交易。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = DatabaseReader(db)
            相依項目須先依 Args 建立。
        """
        self.db = db

    def table_page(self, table, sort=None, direction='asc', offset=0, search='', search_column=None):
        """Whitelist table/column identifiers and return one deterministic page.
        驗證表名與欄位，先搜尋及排序，再回傳最多一百筆資料。

        Args:
            table: 資料表名稱。
            sort: 排序欄位，或 None 使用預設順序。 預設為 None。
            direction: 排序方向，限 asc 或 desc。 預設為 'asc'。
            offset: 略過的資料筆數，須為非負整數。 預設為 0。
            search: 以字面子字串比對的搜尋內容。 預設為 ''。
            search_column: 指定搜尋欄位，或 None 搜尋全部欄位。 預設為 None。

        Returns:
            dict: columns、最多一百筆 rows 及 nextOffset。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> service = DatabaseReader(db)
            >>> result = service.table_page(table=table)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
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


class LogReader:
    """Own a log directory and signing key for snapshot pagination.
    封裝日誌目錄與簽章密鑰，提供快照分頁。
    """

    def __init__(self, directory, secret):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            directory: 要查閱的日誌目錄路徑。
            secret: 日誌快照游標的簽章密鑰。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = LogReader(directory, secret)
            相依項目須先依 Args 建立。
        """
        self.directory = directory
        self.secret = secret

    def log_page(self, cursor=None):
        """Read a signed, byte-bounded snapshot newest first across both retained files.

        File inodes survive rotation; return an expired-snapshot error if a retained
        file is deleted. Never accept a client-provided file path.
        依簽章游標讀取兩份保留日誌的最新快照，檔案失效時要求重新載入。

        Args:
            cursor: 上一頁回傳的簽章游標，首次讀取使用 None。 預設為 None。

        Returns:
            dict: 日誌 rows 與簽章 nextCursor。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
            LookupError: 日誌快照對應檔案已刪除或縮小，須重新載入。 若由下列處理流程捕捉，則依其轉換規則處理。
            BadSignature: 捕捉後轉換為上列業務或驗證例外。
            ValueError, UnicodeDecodeError: 已在函式內捕捉，使用備援流程、略過無效資料或完成清理。

        Example:
            >>> service = LogReader(directory, secret)
            >>> result = service.log_page()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        directory = self.directory
        secret = self.secret
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
