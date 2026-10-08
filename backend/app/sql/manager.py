"""Provide validated SQLite CRUD operations with explicit transaction boundaries."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Mapping, Sequence


_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def identifier(name: str) -> str:
    """Validate a simple SQL identifier and return its double-quoted representation.

    Raise ValueError for unsupported identifiers; bind data values separately.
    驗證 SQL 識別字，並回傳雙引號包覆的名稱。

    Args:
        name (str): 要存取或驗證的名稱。

    Returns:
        str: 驗證後的雙引號 SQL 識別字。

    Exceptions:
        ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = identifier(name=name)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ValueError(f'Invalid SQL identifier: {name!r}')
    return f'"{name}"'


@dataclass(frozen=True)
class Column:
    """Describe a SQLite column using a restricted type and optional constraints."""
    name: str
    type: str = 'TEXT'
    primary_key: bool = False
    nullable: bool = True
    unique: bool = False

    def definition(self):
        """Render a column definition, rejecting unsupported SQLite type names.
        產生欄位 SQL 定義，拒絕不支援的 SQLite 型別。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            str: SQLite 欄位定義。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> result = instance.definition()
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        kind = self.type.upper()
        if kind not in {'INTEGER', 'REAL', 'TEXT', 'BLOB', 'NUMERIC'}:
            raise ValueError('Unsupported SQLite column type')
        return ' '.join(filter(None, [identifier(self.name), kind,
                                      'PRIMARY KEY' if self.primary_key else '',
                                      'NOT NULL' if not self.nullable else '',
                                      'UNIQUE' if self.unique else '']))


class SQLSession:
    """Operations on one transaction. Instances must not escape their context."""
    def __init__(self, connection):
        """Wrap an existing connection whose lifetime is managed by SQLManager.
        包裝由 SQLManager 管理生命週期的 SQLite 連線。

        Args:
            connection: 目前交易使用的 SQLite 連線。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Exceptions:

        Example:
            >>> result = SQLSession(connection=connection)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        self.connection = connection

    def query(self, sql: str, parameters: Sequence | Mapping = ()) -> list[dict]:
        """Run trusted SQL with bound values and materialize result rows.
        使用綁定參數執行 SQL 查詢，將結果轉成字典清單。

        Args:
            sql (str): 可信任的 SQL 敘述，資料值須另外綁定。
            parameters (Sequence | Mapping): SQL 綁定參數序列或對照表。 預設為 ()。

        Returns:
            list[dict]: 查詢結果，無資料時為空清單。

        Exceptions:
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。
            執行期間的例外: finally 完成資源清理後，仍向呼叫者傳遞。

        Example:
            >>> result = instance.query(sql="SELECT userId FROM member LIMIT 1")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        cursor = self.connection.execute(sql, parameters)
        try:
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def execute(self, sql: str, parameters: Sequence | Mapping = ()) -> dict:
        """Run one trusted statement; do not supply transaction-control SQL.
        執行單一 SQL 敘述並回傳受影響筆數與最後新增列編號。

        Args:
            sql (str): 可信任的 SQL 敘述，資料值須另外綁定。
            parameters (Sequence | Mapping): SQL 綁定參數序列或對照表。 預設為 ()。

        Returns:
            dict: 包含 rowcount 與 lastrowid 的執行結果。

        Exceptions:
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。
            執行期間的例外: finally 完成資源清理後，仍向呼叫者傳遞。

        Example:
            >>> result = instance.execute(sql="SELECT userId FROM member LIMIT 1")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        cursor = self.connection.execute(sql, parameters)
        try:
            return {'rowcount': cursor.rowcount, 'lastrowid': cursor.lastrowid}
        finally:
            cursor.close()

    def create_table(self, table: str, columns: Sequence[Column]):
        """Create a table if absent, requiring a nonempty set of uniquely named columns.
        檢查欄位名稱後，建立尚不存在的資料表。

        Args:
            table (str): 資料表名稱。
            columns (Sequence[Column]): 要建立或查詢的欄位清單。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.create_table(table="member", columns=columns)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if not columns or len({column.name for column in columns}) != len(columns):
            raise ValueError('Provide nonempty, unique column names')
        definitions = ', '.join(column.definition() for column in columns)
        self.execute(f'CREATE TABLE IF NOT EXISTS {identifier(table)} ({definitions})')

    def insert(self, table: str, values: Mapping):
        """Insert bound column values and return SQLite's lastrowid.

        Reject an empty mapping; lastrowid is not necessarily the application's primary key.
        以綁定參數新增資料，回傳 SQLite 列編號而非業務 UUID。

        Args:
            table (str): 資料表名稱。
            values (Mapping): 欄位名稱與資料值的對照表。

        Returns:
            int: SQLite lastrowid；不代表業務主鍵 UUID。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.insert(table="member", values=values)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if not values:
            raise ValueError('Insert requires values')
        columns = ', '.join(identifier(key) for key in values)
        placeholders = ', '.join('?' for _ in values)
        return self.execute(f'INSERT INTO {identifier(table)} ({columns}) VALUES ({placeholders})',
                            tuple(values.values()))['lastrowid']

    @staticmethod
    def _where(where):
        """Build equality filters and bound values, using IS NULL for None values.
        將等值篩選條件轉為 SQL 與綁定參數，空值使用 IS NULL。

        Args:
            where: 等值篩選對照表；None 表示無篩選。

        Returns:
            tuple[str, list]: WHERE SQL 片段與綁定參數。

        Exceptions:

        Example:
            >>> result = instance._where(where=where)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if not where:
            return '', []
        clauses, values = [], []
        for key, value in where.items():
            name = identifier(key)
            clauses.append(f'{name} IS NULL' if value is None else f'{name} = ?')
            if value is not None:
                values.append(value)
        return ' WHERE ' + ' AND '.join(clauses), values

    def select(self, table: str, where: Mapping | None = None, *,
               columns: Sequence[str] | None = None, order_by: str | None = None,
               descending: bool = False, limit: int | None = None, offset: int = 0):
        """Return matching rows as dictionaries with optional projection and pagination.

        Validate identifiers and nonnegative integer limits. An empty filter selects all rows.
        依欄位、條件、排序與分頁設定查詢資料列。

        Args:
            table (str): 資料表名稱。
            where (Mapping | None): 等值篩選對照表；None 表示無篩選。 預設為 None。
            columns (Sequence[str] | None): 要建立或查詢的欄位清單。 預設為 None。
            order_by (str | None): 排序欄位名稱，或 None。 預設為 None。
            descending (bool): 是否採用降冪排序。 預設為 False。
            limit (int | None): 最多回傳筆數，或 None 表示不限制。 預設為 None。
            offset (int): 略過的資料筆數，須為非負整數。 預設為 0。

        Returns:
            list[dict]: 符合條件的資料列。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.select(table="member")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if columns is not None and not columns:
            raise ValueError('Columns cannot be empty')
        fields = ', '.join(identifier(column) for column in columns) if columns else '*'
        condition, values = self._where(where)
        sql = f'SELECT {fields} FROM {identifier(table)}{condition}'
        if order_by:
            sql += f' ORDER BY {identifier(order_by)} ' + ('DESC' if descending else 'ASC')
        for name, value in [('limit', limit), ('offset', offset)]:
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f'{name} must be a nonnegative integer')
        if limit is not None or offset:
            sql += ' LIMIT ? OFFSET ?'
            values.extend([limit if limit is not None else -1, offset])
        return self.query(sql, values)

    def update(self, table: str, values: Mapping, where: Mapping | None = None, *, all_rows=False):
        """Update matching rows and return the affected-row count.

        Require a filter unless all_rows=True explicitly authorizes a full-table update.
        更新符合條件的資料，整表更新必須明確指定 all_rows。

        Args:
            table (str): 資料表名稱。
            values (Mapping): 欄位名稱與資料值的對照表。
            where (Mapping | None): 等值篩選對照表；None 表示無篩選。 預設為 None。
            all_rows: 是否明確允許異動所有資料列。 預設為 False。

        Returns:
            int: 受影響資料筆數。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.update(table="member", values=values)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if not values:
            raise ValueError('Update requires values')
        if not where and not all_rows:
            raise ValueError('Update requires a filter or explicit all_rows=True')
        condition, parameters = self._where(where)
        assignments = ', '.join(f'{identifier(key)} = ?' for key in values)
        return self.execute(f'UPDATE {identifier(table)} SET {assignments}{condition}',
                            [*values.values(), *parameters])['rowcount']

    def delete(self, table: str, where: Mapping | None = None, *, all_rows=False):
        """Delete matching rows and return the affected-row count.

        Require a filter unless all_rows=True explicitly authorizes a full-table deletion.
        刪除符合條件的資料，整表刪除必須明確指定 all_rows。

        Args:
            table (str): 資料表名稱。
            where (Mapping | None): 等值篩選對照表；None 表示無篩選。 預設為 None。
            all_rows: 是否明確允許異動所有資料列。 預設為 False。

        Returns:
            int: 刪除資料筆數。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.delete(table="member")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if not where and not all_rows:
            raise ValueError('Delete requires a filter or explicit all_rows=True')
        condition, parameters = self._where(where)
        return self.execute(f'DELETE FROM {identifier(table)}{condition}', parameters)['rowcount']

    def list_tables(self):
        """Return sorted user table names, excluding SQLite's internal tables.
        列出依名稱排序的使用者資料表，排除 SQLite 內部資料表。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            list[str]: 使用者資料表名稱。

        Exceptions:
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.list_tables()
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        return [row['name'] for row in self.query(
            "SELECT name FROM sqlite_schema WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    def table_exists(self, table: str):
        """Check whether a validated table name exists in the database schema.
        驗證資料表名稱並檢查其是否存在。

        Args:
            table (str): 資料表名稱。

        Returns:
            bool: 指定資料表是否存在。

        Exceptions:
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.table_exists(table="member")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        identifier(table)
        return bool(self.query("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)))

    def table_status(self, table: str):
        """Return row count, columns, indexes, keys, and SQL, or an absent-table result.
        取得資料表筆數、欄位、索引、外鍵與建表 SQL。

        Args:
            table (str): 資料表名稱。

        Returns:
            dict: 資料表結構與筆數，或 exists=False 的結果。

        Exceptions:
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.table_status(table="member")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        name = identifier(table)
        if not self.table_exists(table):
            return {'name': table, 'exists': False}
        return {
            'name': table, 'exists': True,
            'row_count': self.query(f'SELECT COUNT(*) AS count FROM {name}')[0]['count'],
            'columns': self.query(f'PRAGMA table_info({name})'),
            'indexes': self.query(f'PRAGMA index_list({name})'),
            'foreign_keys': self.query(f'PRAGMA foreign_key_list({name})'),
            'sql': self.query('SELECT sql FROM sqlite_schema WHERE type=\'table\' AND name=?',
                              (table,))[0]['sql'],
        }

    def database_status(self):
        """Report integrity, foreign-key violations, tables, allocated bytes, and journal mode.
        回報資料庫完整性、外鍵違規、容量及日誌模式。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            dict: 資料庫完整性與容量狀態。

        Exceptions:
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> result = instance.database_status()
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        integrity = [row['quick_check'] for row in self.query('PRAGMA quick_check')]
        foreign_key_violations = self.query('PRAGMA foreign_key_check')
        page_count = self.query('PRAGMA page_count')[0]['page_count']
        page_size = self.query('PRAGMA page_size')[0]['page_size']
        return {'healthy': integrity == ['ok'] and not foreign_key_violations,
                'integrity': integrity, 'foreign_key_violations': foreign_key_violations,
                'tables': self.list_tables(), 'size_bytes': page_count * page_size,
                'journal_mode': self.query('PRAGMA journal_mode')[0]['journal_mode']}


class SQLManager:
    """File-backed database; separate connection per operation or transaction."""
    def __init__(self, path: str | Path, timeout: float = 10):
        """Configure a database path and lock timeout without creating the database.

        Reject :memory: because each operation uses its own connection.
        設定檔案型資料庫路徑與鎖等候時間，不立即建立資料庫。

        Args:
            path (str | Path): 資料庫檔案路徑；不接受 :memory:。
            timeout (float): 等待 SQLite 鎖的秒數。 預設為 10。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> result = SQLManager(path=path)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if str(path) == ':memory:':
            raise ValueError('SQLManager requires a file-backed database')
        self.path = Path(path)
        self.timeout = timeout

    @contextmanager
    def transaction(self, *, immediate=False):
        """Yield a SQLSession on a fresh connection with foreign keys enabled.

        Create parent directories as needed. Commit on success, roll back on any
        exception, and always close the connection when the context exits.
        Set immediate=True to acquire the write lock before a read-then-write operation.
        開啟獨立交易並提供 SQLSession，成功提交，失敗回滾，最後關閉連線。

        Args:
            immediate: 是否在讀寫前先透過 BEGIN IMMEDIATE 取得寫入鎖。 預設為 False。

        Returns:
            ContextManager[SQLSession]: with 區塊內使用的交易工作階段。

        Exceptions:
            BaseException: 捕捉後完成清理或回滾，再將原例外向外拋出。
            sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

        Example:
            >>> with instance.transaction() as context:
            ...     pass
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN')
            yield SQLSession(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def __getattr__(self, name):
        # Expose the same operations as a session, with automatic commit/rollback.
        """Wrap a public SQLSession operation in its own automatically managed transaction.
        為公開 SQLSession 方法建立自動管理交易的代理函式。

        Args:
            name: 要存取或驗證的名稱。

        Returns:
            Callable: 自動開啟交易的 SQL 方法代理。

        Exceptions:
            AttributeError: 指定方法不是可代理的公開 SQLSession 方法。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> result = instance.__getattr__(name=name)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if name.startswith('_') or not callable(getattr(SQLSession, name, None)):
            raise AttributeError(name)
        def operation(*args, **kwargs):
            """Execute the selected session method within a fresh transaction.
            在新交易內呼叫選定的 SQLSession 方法。

            Args:
                args: 轉交被呼叫方法的位置參數。
                kwargs: 轉交被呼叫方法的關鍵字參數。

            Returns:
                object: 被代理 SQLSession 方法的回傳結果。

            Exceptions:
                sqlite3.Error: SQL 執行或交易失敗時向外傳遞。

            Example:
                >>> result = operation(*args, **kwargs)
                db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
            """
            with self.transaction() as session:
                return getattr(session, name)(*args, **kwargs)
        return operation
