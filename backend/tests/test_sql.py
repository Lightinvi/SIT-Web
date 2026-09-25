from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app import create_app
from app.sql import Column, SQLManager


class SQLTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'database' / 'test.sqlite3'
        self.db = SQLManager(self.path)
        self.db.create_table('members', [Column('id', 'INTEGER', primary_key=True),
                                      Column('name', nullable=False, unique=True),
                                      Column('note')])

    def test_crud_and_persistence(self):
        key = self.db.insert('members', {'name': '隊員', 'note': None})
        self.assertEqual(self.db.select('members', {'id': key})[0]['name'], '隊員')
        self.assertEqual(self.db.update('members', {'name': '新名稱'}, {'id': key}), 1)
        self.assertEqual(SQLManager(self.path).select('members')[0]['name'], '新名稱')
        self.assertEqual(self.db.delete('members', {'id': key}), 1)
        self.assertEqual(self.db.select('members'), [])

    def test_filters_order_and_pagination(self):
        for i in range(4):
            self.db.insert('members', {'name': str(i), 'note': None if i < 2 else 'yes'})
        self.assertEqual(len(self.db.select('members', {'note': None})), 2)
        rows = self.db.select('members', columns=['name'], order_by='id', descending=True, limit=2, offset=1)
        self.assertEqual(rows, [{'name': '2'}, {'name': '1'}])
        self.assertEqual(len(self.db.select('members', offset=3)), 1)
        with self.assertRaises(ValueError):
            self.db.select('members', limit=-1)

    def test_transaction_rollback_including_schema(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as tx:
                tx.create_table('temporary_table', [Column('id', 'INTEGER')])
                tx.insert('members', {'name': 'duplicate'})
                tx.insert('members', {'name': 'duplicate'})
        self.assertEqual(self.db.select('members'), [])
        self.assertFalse(self.db.table_exists('temporary_table'))
        with self.db.transaction() as tx:
            tx.insert('members', {'name': 'committed'})
            self.assertEqual(len(tx.select('members')), 1)
        self.assertEqual(len(self.db.select('members')), 1)

    def test_injection_and_mass_mutation_guards(self):
        malicious = "x'); DROP TABLE members; --"
        self.db.insert('members', {'name': malicious})
        self.assertEqual(self.db.select('members', {'name': malicious})[0]['name'], malicious)
        with self.assertRaises(ValueError):
            self.db.select('members; DROP TABLE members')
        with self.assertRaises(ValueError):
            self.db.update('members', {'note': 'all'})
        with self.assertRaises(ValueError):
            self.db.delete('members', {})
        self.assertEqual(self.db.update('members', {'note': 'all'}, all_rows=True), 1)
        self.assertEqual(self.db.delete('members', all_rows=True), 1)

    def test_schema_and_database_health(self):
        self.db.insert('members', {'name': 'test'})
        self.assertEqual(self.db.list_tables(), ['members'])
        status = self.db.table_status('members')
        self.assertTrue(status['exists'])
        self.assertEqual(status['row_count'], 1)
        self.assertEqual([c['name'] for c in status['columns']], ['id', 'name', 'note'])
        self.assertTrue(status['indexes'])
        self.assertEqual(self.db.table_status('missing'), {'name': 'missing', 'exists': False})
        self.assertTrue(self.db.database_status()['healthy'])

    def test_foreign_keys_and_parameterized_sql(self):
        self.db.execute('CREATE TABLE links (member_id INTEGER REFERENCES members(id))')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO links VALUES (?)', (999,))
        self.assertEqual(self.db.query('SELECT :value AS value', {'value': '測試'}), [{'value': '測試'}])
        self.assertEqual(len(self.db.table_status('links')['foreign_keys']), 1)

    def test_app_factory_isolation_and_lazy_creation(self):
        other = Path(self.temp.name) / 'other.sqlite3'
        app = create_app({'TESTING': True, 'SQL_DATABASE_PATH': str(other)})
        self.assertFalse(other.exists())
        self.assertNotEqual(app.extensions['sql'].path, self.db.path)
        self.assertEqual(app.extensions['sql'].list_tables(), [])
        self.assertTrue(other.exists())

    def test_invalid_schema(self):
        with self.assertRaises(ValueError):
            self.db.create_table('bad', [])
        with self.assertRaises(ValueError):
            self.db.create_table('bad', [Column('name', 'TEXT; DROP TABLE members')])
        with self.assertRaises(ValueError):
            self.db.insert('members', {})
