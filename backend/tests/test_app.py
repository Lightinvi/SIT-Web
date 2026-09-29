"""Verify app isolation and the basic public API contracts."""
import unittest

from app import create_app


class AppTests(unittest.TestCase):
    """Exercise factory-created applications using Flask test clients."""
    def setUp(self):
        """Create an isolated testing app and client for each API check."""
        self.app = create_app({"TESTING": True})
        self.client = self.app.test_client()

    def test_users_with_and_without_trailing_slash(self):
        """Verify both URL spellings return the complete demo-user schema."""
        for path in ("/api/users", "/api/users/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                users = response.json["users"]
                self.assertEqual(len(users), 3)
                self.assertEqual(users[0]["name"], "Alex Chen")
                self.assertEqual(len({user["id"] for user in users}), 3)
                for user in users:
                    self.assertEqual(set(user), {"id", "name", "email", "role", "status"})
                    self.assertIn(user["status"], ("active", "invited"))

    def test_session_is_anonymous(self):
        """Verify an unauthenticated client receives an anonymous session response."""
        response = self.client.get("/api/auth/session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"authenticated": False})

    def test_factory_creates_independent_apps(self):
        """Verify factory calls produce independent app instances and configuration."""
        other = create_app({"TESTING": True, "SECRET_KEY": "other"})
        self.assertIsNot(self.app, other)
        self.assertNotEqual(self.app.config["SECRET_KEY"], other.config["SECRET_KEY"])
