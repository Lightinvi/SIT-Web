"""Verify role ordering and conservative handling of old login snapshots."""
import unittest

from app.services.roles import ACCESS_ROLES, highest_role


class RoleTests(unittest.TestCase):
    """Keep permission labels and highest-role selection consistent."""

    def test_priority_and_individual_roles(self):
        """Each role wins over all lower roles, regardless of input order."""
        for index, role in enumerate(ACCESS_ROLES):
            self.assertEqual(highest_role([role['id']]), role)
            self.assertEqual(highest_role([item['id'] for item in reversed(ACCESS_ROLES[index:])]), role)

    def test_unknown_or_malformed_roles_grant_none(self):
        """Never infer permission from absent, unrelated, or malformed role IDs."""
        for value in (None, [], ['unknown'], ACCESS_ROLES[0]['id'], [None], [[1]]):
            self.assertIsNone(highest_role(value))
