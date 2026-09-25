from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Mapping, Sequence


_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def identifier(name: str) -> str:
    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ValueError(f'Invalid SQL identifier: {name!r}')
    return f'"{name}"'


@dataclass(frozen=True)
class Column:
    name: str
    type: str = 'TEXT'
    primary_key: bool = False
    nullable: bool = True
    unique: bool = False

    def definition(self):
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
        self.connection = connection

    def query(self, sql: str, parameters: Sequence | Mapping = ()) -> list[dict]:
        """Run trusted SQL with bound values and materialize result rows."""
        cursor = self.connection.execute(sql, parameters)
        try:
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def execute(self, sql: str, parameters: Sequence | Mapping = ()) -> dict:
        """Run one trusted statement; do not supply transaction-control SQL."""
        cursor = self.connection.execute(sql, parameters)
        try:
            return {'rowcount': cursor.rowcount, 'lastrowid': cursor.lastrowid}
        finally:
            cursor.close()

    def create_table(self, table: str, columns: Sequence[Column]):
        if not columns or len({column.name for column in columns}) != len(columns):
            raise ValueError('Provide nonempty, unique column names')
        definitions = ', '.join(column.definition() for column in columns)
        self.execute(f'CREATE TABLE IF NOT EXISTS {identifier(table)} ({definitions})')

    def insert(self, table: str, values: Mapping):
        if not values:
            raise ValueError('Insert requires values')
        columns = ', '.join(identifier(key) for key in values)
        placeholders = ', '.join('?' for _ in values)
        return self.execute(f'INSERT INTO {identifier(table)} ({columns}) VALUES ({placeholders})',
                            tuple(values.values()))['lastrowid']

    @staticmethod
    def _where(where):
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
        if not values:
            raise ValueError('Update requires values')
        if not where and not all_rows:
            raise ValueError('Update requires a filter or explicit all_rows=True')
        condition, parameters = self._where(where)
        assignments = ', '.join(f'{identifier(key)} = ?' for key in values)
        return self.execute(f'UPDATE {identifier(table)} SET {assignments}{condition}',
                            [*values.values(), *parameters])['rowcount']

    def delete(self, table: str, where: Mapping | None = None, *, all_rows=False):
        if not where and not all_rows:
            raise ValueError('Delete requires a filter or explicit all_rows=True')
        condition, parameters = self._where(where)
        return self.execute(f'DELETE FROM {identifier(table)}{condition}', parameters)['rowcount']

    def list_tables(self):
        return [row['name'] for row in self.query(
            "SELECT name FROM sqlite_schema WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    def table_exists(self, table: str):
        identifier(table)
        return bool(self.query("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)))

    def table_status(self, table: str):
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
        if str(path) == ':memory:':
            raise ValueError('SQLManager requires a file-backed database')
        self.path = Path(path)
        self.timeout = timeout

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('BEGIN')
            yield SQLSession(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def __getattr__(self, name):
        # Expose the same operations as a session, with automatic commit/rollback.
        if name.startswith('_') or not callable(getattr(SQLSession, name, None)):
            raise AttributeError(name)
        def operation(*args, **kwargs):
            with self.transaction() as session:
                return getattr(session, name)(*args, **kwargs)
        return operation
