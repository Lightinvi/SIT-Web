"""Verify severity filtering, request privacy, UTF-8 limits, and worker-safe rotation."""
import json
import logging
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app import create_app
from app.logging_setup import BoundedFileHandler, JsonFormatter, MAX_LOG_BYTES


def write_worker(directory, worker, count, limit):
    """Emit independent-process JSON records into the same rotating files.
    由獨立程序寫入指定數量的日誌，供共享輪替測試使用。

    Args:
        directory: 日誌儲存目錄。
        worker: 測試寫入程序的識別碼。
        count: 要建立的測試紀錄數量。
        limit: 每份測試日誌的最大位元組數。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
        對應測試或輔助流程：test_logging。
    """
    logger = logging.Logger('worker', logging.INFO)
    handler = BoundedFileHandler(directory, limit)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    for index in range(count):
        logger.info('worker=%s event=%s 測試', worker, index)
    handler.close()


class LoggingTests(unittest.TestCase):
    """Run logging checks without touching the application's persistent log directory."""

    def setUp(self):
        """Enable file logging only for this test's temporary app instance.
        建立此測試案例所需的獨立環境與測試資料。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests。
        """
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'LOG_ENABLED': True, 'SECRET_KEY': 'test',
            'LOG_DIRECTORY': self.temp.name,
            'SQL_DATABASE_PATH': str(Path(self.temp.name) / 'test.sqlite3')})

    def events(self):
        """Read complete JSON lines from both retained log files.
        讀取測試目錄內的 JSON 日誌事件。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            list[dict]: 測試儲存目錄中的日誌事件。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests。
        """
        return [json.loads(line) for path in Path(self.temp.name).glob('app.log*')
                for line in path.read_text().splitlines()]

    def test_default_severities_and_request_correlation(self):
        """Keep INFO and higher, with generated IDs and no OAuth query/body credentials.
        驗證預設日誌等級及請求關聯識別碼。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests.test_default_severities_and_request_correlation。
        """
        self.app.logger.debug('debug-omitted')
        self.app.logger.info('info-event')
        self.app.logger.warning('warning-event')
        self.app.logger.error('error-event')
        client = self.app.test_client()
        response = client.get('/api/auth/session?code=secret-oauth-code', headers={'Authorization': 'secret-token'})
        denied = client.post('/api/auth/logout', json={'secret': 'secret-body'})
        self.assertEqual(denied.status_code, 403)
        events = self.events()
        self.assertEqual([event['level'] for event in events[:3]], ['INFO', 'WARNING', 'ERROR'])
        self.assertEqual(events[3]['requestId'], response.headers['X-Request-ID'])
        self.assertEqual(events[4]['level'], 'WARNING')
        self.assertEqual(events[3]['route'], '/api/auth/session')
        self.assertNotIn('secret-', str(events))
        self.assertNotIn('debug-omitted', str(events))

    def test_byte_limit_and_two_total_files(self):
        """Never exceed encoded-byte limits, including a single huge Unicode event.
        驗證日誌位元組上限與最多兩份檔案。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests.test_byte_limit_and_two_total_files。
        """
        handler = self.app.logger.handlers[0]
        self.assertEqual(handler.max_bytes, MAX_LOG_BYTES)
        handler.max_bytes = 1024
        for _ in range(80):
            self.app.logger.info('多位元組文字' * 40)
        self.app.logger.error('巨量文字' * 10000)
        files = list(Path(self.temp.name).glob('app.log*'))
        self.assertEqual({path.name for path in files}, {'app.log', 'app.log.1'})
        self.assertTrue(all(path.stat().st_size <= 1024 for path in files))
        self.assertTrue(any(event.get('truncated') for event in self.events()))

    def test_health_success_is_quiet(self):
        """Health probes remain public, correlated, and absent from successful request logs.
        驗證健康檢查成功時省略日誌。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests.test_health_success_is_quiet。
        """
        client = self.app.test_client()
        for method in (client.get, client.head):
            response = method('/api/health')
            self.assertEqual(response.status_code, 200)
            self.assertIn('X-Request-ID', response.headers)
        self.assertEqual(client.get('/api/health').json, {'status': 'ok'})
        self.assertEqual(self.events(), [])
        client.get('/api/users')
        self.assertEqual(self.events()[-1]['route'], '/api/users')

    def test_health_failures_are_logged(self):
        """Do not hide failed probes, unsupported methods, or similar missing routes.
        驗證健康檢查失敗仍保留日誌。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests.test_health_failures_are_logged。
        """
        client = self.app.test_client()
        client.post('/api/health')
        client.get('/api/health-missing')
        self.app.view_functions['health'] = lambda: ({'status': 'unavailable'}, 503)
        response = client.get('/api/health')
        self.assertEqual(response.status_code, 503)
        self.assertEqual([event['level'] for event in self.events()], ['WARNING', 'WARNING', 'ERROR'])
        self.assertEqual(self.events()[-1]['requestId'], response.headers['X-Request-ID'])

    def test_multiple_processes_share_complete_records(self):
        """Separate workers preserve every event when rotation is not needed.
        驗證多程序寫入保留完整日誌。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests.test_multiple_processes_share_complete_records。
        """
        workers = [get_context('fork').Process(target=write_worker, args=(self.temp.name, index, 50, MAX_LOG_BYTES)) for index in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(len(self.events()), 200)
        self.assertEqual(len({event['message'] for event in self.events()}), 200)

    def test_multiple_processes_rotate_safely(self):
        """Concurrent rotations still leave at most two bounded, valid JSON log files.
        驗證多程序日誌輪替一致性。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests.test_multiple_processes_rotate_safely。
        """
        workers = [get_context('fork').Process(target=write_worker, args=(self.temp.name, index, 80, 1024)) for index in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            self.assertEqual(worker.exitcode, 0)
        files = list(Path(self.temp.name).glob('app.log*'))
        self.assertEqual(len(files), 2)
        self.assertTrue(all(path.stat().st_size <= 1024 for path in files))
        self.assertTrue(self.events())

    def test_application_loggers_are_isolated(self):
        """A second app does not reuse the first app's handlers or duplicate its events.
        驗證各應用程式日誌器隔離。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests.test_application_loggers_are_isolated。
        """
        other = create_app({'TESTING': True})
        other.logger.info('other-app')
        self.app.logger.info('this-app')
        self.assertEqual([event['message'] for event in self.events()], ['this-app'])

    def test_errors_include_frames_without_exception_values(self):
        """Retain a request ID and stack location while omitting sensitive exception text.
        驗證錯誤保留堆疊位置且不洩漏例外值。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
            對應測試或輔助流程：test_logging.LoggingTests.test_errors_include_frames_without_exception_values。
        """
        @self.app.get('/test-error')
        def fail():
            """Raise an exception containing a value that must not enter a traceback log.
            刻意拋出含敏感內容的錯誤，供日誌脫敏測試使用。

            Args:
                None: 無需傳入參數；實例方法使用目前物件狀態。

            Returns:
                None: 僅更新狀態或執行副作用，不回傳資料。

            Exceptions:
                ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。

            Example:
                在 backend 目錄執行：python -m unittest discover -s tests -p "test_logging.py"
                對應測試或輔助流程：test_logging.LoggingTests.test_errors_include_frames_without_exception_values。
            """
            raise ValueError('secret-exception-value')
        self.app.config['PROPAGATE_EXCEPTIONS'] = False
        response = self.app.test_client().get('/test-error')
        self.assertEqual(response.status_code, 500)
        events = self.events()
        self.assertEqual(events[0]['exceptionType'], 'ValueError')
        self.assertTrue(events[0]['traceback'])
        self.assertEqual(events[-1]['level'], 'ERROR')
        self.assertNotIn('secret-exception-value', str(events))
