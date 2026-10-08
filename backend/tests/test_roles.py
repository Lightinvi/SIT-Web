"""Verify role ordering and conservative handling of old login snapshots."""
import unittest

from app.services.roles import ACCESS_ROLES, highest_role


class RoleTests(unittest.TestCase):
    """Keep permission labels and highest-role selection consistent."""

    def test_priority_and_individual_roles(self):
        """Each role wins over all lower roles, regardless of input order.
        驗證身份組優先序及各身份權限。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_roles.py"
            對應測試或輔助流程：test_roles.RoleTests.test_priority_and_individual_roles。
        """
        for index, role in enumerate(ACCESS_ROLES):
            self.assertEqual(highest_role([role['id']]), role)
            self.assertEqual(highest_role([item['id'] for item in reversed(ACCESS_ROLES[index:])]), role)

    def test_unknown_or_malformed_roles_grant_none(self):
        """Never infer permission from absent, unrelated, or malformed role IDs.
        驗證未知或無效身份組不授予權限。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_roles.py"
            對應測試或輔助流程：test_roles.RoleTests.test_unknown_or_malformed_roles_grant_none。
        """
        for value in (None, [], ['unknown'], ACCESS_ROLES[0]['id'], [None], [[1]]):
            self.assertIsNone(highest_role(value))
