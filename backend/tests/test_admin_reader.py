"""Verify administration readers, pagination, ordering, and live access protection."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_admin
from app.services.admin_reader import log_page


class AdminReaderTests(unittest.TestCase):
    """Reuse isolated authenticated fixtures without accessing production data."""

    setUp = test_admin.AdminTests.setUp

    def test_all_read_routes_require_live_web_admin(self):
        """Reject anonymous users and live demotions even with a stored admin role.
        驗證所有管理查閱路由要求即時網頁管理員身份。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_admin_reader.py"
            對應測試或輔助流程：test_admin_reader.AdminReaderTests.test_all_read_routes_require_live_web_admin。
        """
        for path in ('/api/admin/database', '/api/admin/database/member', '/api/admin/log'):
            self.assertEqual(self.app.test_client().get(path).status_code, 401)
            with patch.object(self.service, '_request', return_value={'user': {'id': '111'}, 'roles': [test_admin.MEMBER]}):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_database_paging_sorting_and_injection(self):
        """Return exactly 100 rows per page and reject untrusted identifiers/directions.
        驗證管理資料庫分頁、排序及注入防護。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_admin_reader.py"
            對應測試或輔助流程：test_admin_reader.AdminReaderTests.test_database_paging_sorting_and_injection。
        """
        self.db.execute('CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)')
        with self.db.transaction() as tx:
            for number in range(205):
                tx.insert('sample', {'id': number, 'value': str(number)})
        with patch.object(self.service, '_request', return_value=self.live):
            self.assertIn('sample', self.client.get('/api/admin/database').json['tables'])
            first = self.client.get('/api/admin/database/sample?sort=id&direction=desc')
            self.assertEqual(first.headers['Cache-Control'], 'no-store')
            self.assertEqual(len(first.json['rows']), 100)
            self.assertEqual(first.json['rows'][0]['id'], 204)
            second = self.client.get('/api/admin/database/sample?sort=id&direction=desc&offset=100').json
            self.assertEqual(second['rows'][0]['id'], 104)
            last = self.client.get('/api/admin/database/sample?offset=200').json
            self.assertEqual(len(last['rows']), 5)
            self.assertIsNone(last['nextOffset'])
            for suffix in ('sample?sort=id;DROP%20TABLE%20sample', 'sample?direction=invalid', 'sample?offset=-1', 'missing'):
                self.assertEqual(self.client.get('/api/admin/database/' + suffix).status_code, 400)
        self.assertTrue(self.db.table_exists('sample'))

    def test_log_snapshot_survives_append_and_rotation(self):
        """A cursor continues the original snapshot, skipping malformed JSON lines.
        驗證日誌追加與輪替後仍可讀取保留的快照。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_admin_reader.py"
            對應測試或輔助流程：test_admin_reader.AdminReaderTests.test_log_snapshot_survives_append_and_rotation。
        """
        directory = Path(self.temp.name) / 'logs'
        directory.mkdir()
        path = directory / 'app.log'
        path.write_text('\n'.join(json.dumps({'message': str(i), 'level': 'INFO'}) for i in range(205)) + '\nbroken\n')
        first = log_page(directory, 'test')
        self.assertEqual(len(first['rows']), 100)
        self.assertEqual(first['rows'][0]['message'], '204')
        with path.open('a') as stream:
            stream.write(json.dumps({'message': 'new'}) + '\n')
        path.rename(directory / 'app.log.1')
        path.write_text(json.dumps({'message': 'newer'}) + '\n')
        second = log_page(directory, 'test', first['nextCursor'])
        self.assertEqual(second['rows'][0]['message'], '104')
        last = log_page(directory, 'test', second['nextCursor'])
        self.assertEqual(len(last['rows']), 5)
        self.assertIsNone(last['nextCursor'])
        (directory / 'app.log.1').unlink()
        with self.assertRaises(LookupError):
            log_page(directory, 'test', first['nextCursor'])
        with self.assertRaises(ValueError):
            log_page(directory, 'test', 'tampered')

    def test_content_search_is_literal_and_precedes_pagination(self):
        """Search all stored rows and columns, keeping sorting and literal SQL characters.
        驗證欄位內容搜尋採字面比對且先於分頁。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_admin_reader.py"
            對應測試或輔助流程：test_admin_reader.AdminReaderTests.test_content_search_is_literal_and_precedes_pagination。
        """
        self.db.execute('CREATE TABLE searchable (id INTEGER PRIMARY KEY, description TEXT, note TEXT)')
        with self.db.transaction() as tx:
            for number in range(205):
                tx.insert('searchable', {'id': number, 'description': 'MATCH', 'note': '特殊%_內容' if number == 204 else None})
        with patch.object(self.service, '_request', return_value=self.live):
            path = '/api/admin/database/searchable'
            first = self.client.get(path, query_string={'q': 'match', 'sort': 'id', 'direction': 'desc'}).json
            self.assertEqual(len(first['rows']), 100)
            self.assertEqual(first['rows'][0]['id'], 204)
            second = self.client.get(path, query_string={'q': 'match', 'offset': 100, 'sort': 'id', 'direction': 'desc'}).json
            self.assertEqual(second['rows'][0]['id'], 104)
            for query in ('特殊', '%_', '204'):
                result = self.client.get(path, query_string={'q': query}).json
                self.assertEqual([row['id'] for row in result['rows']], [204])
            self.assertEqual(self.client.get(path, query_string={'q': "' OR 1=1 --"}).json['rows'], [])
            self.assertEqual(self.client.get(path, query_string={'q': 'x' * 501}).status_code, 400)
            scoped = self.client.get(path, query_string={'q': '204', 'column': 'id'}).json
            self.assertEqual([row['id'] for row in scoped['rows']], [204])
            self.assertEqual(self.client.get(path, query_string={'q': '204', 'column': 'description'}).json['rows'], [])
            self.assertEqual(len(self.client.get(path, query_string={'q': 'match', 'column': 'description', 'offset': 100}).json['rows']), 100)
            for column in ('missing', 'id; DROP TABLE searchable'):
                self.assertEqual(self.client.get(path, query_string={'q': '204', 'column': column}).status_code, 400)

    def test_logs_empty_and_api_fields(self):
        """Missing logs are empty and only the expected JSON fields are exposed.
        驗證空日誌與 API 欄位格式。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_admin_reader.py"
            對應測試或輔助流程：test_admin_reader.AdminReaderTests.test_logs_empty_and_api_fields。
        """
        directory = Path(self.temp.name) / 'logs'
        self.app.config['LOG_DIRECTORY'] = str(directory)
        with patch.object(self.service, '_request', return_value=self.live):
            self.assertEqual(self.client.get('/api/admin/log').json['rows'], [])
            directory.mkdir()
            (directory / 'app.log').write_text(json.dumps({'message': '<script>alert(1)</script>', 'pid': 123}) + '\n')
            response = self.client.get('/api/admin/log')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json['rows'][0]), {'timestamp', 'level', 'requestId', 'message', 'route', 'method', 'status', 'durationMs'})
