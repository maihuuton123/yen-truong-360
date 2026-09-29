import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.dependencies import get_db
from app.main import create_app
from app.models import User


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
        self.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.seed_users()

        self.previous_secret = settings.auth_secret_key
        self.previous_expiration = settings.auth_token_expire_seconds
        settings.auth_secret_key = "unit-test-secret-key-change-me"
        settings.auth_token_expire_seconds = 900
        security.reset_revoked_tokens()

        app = create_app()
        app.dependency_overrides[get_db] = self.override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        settings.auth_secret_key = self.previous_secret
        settings.auth_token_expire_seconds = self.previous_expiration
        security.reset_revoked_tokens()
        self.temp_dir.cleanup()

    def override_get_db(self):
        db = self.SessionTesting()
        try:
            yield db
        finally:
            db.close()

    def seed_users(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    User(
                        username="admin",
                        password_hash=hash_password("admin-password"),
                        full_name="Admin",
                        role="ADMIN",
                        is_active=True,
                    ),
                    User(
                        username="receiver",
                        password_hash=hash_password("receiver-password"),
                        full_name="Receiver",
                        role="RECEIVER",
                        is_active=True,
                    ),
                    User(
                        username="handler",
                        password_hash=hash_password("handler-password"),
                        full_name="Handler",
                        role="HANDLER",
                        is_active=True,
                    ),
                    User(
                        username="inactive",
                        password_hash=hash_password("inactive-password"),
                        full_name="Inactive",
                        role="ADMIN",
                        is_active=False,
                    ),
                ]
            )
            db.commit()

    def login(self, username="admin", password="admin-password"):
        return self.client.post("/api/auth/login", json={"username": username, "password": password})

    def auth_headers(self, username="admin", password="admin-password"):
        response = self.login(username, password)
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_login_success_returns_token_and_user_without_password_hash(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token_type"], "bearer")
        self.assertIn("access_token", body)
        self.assertEqual(body["expires_in"], 900)
        self.assertEqual(body["user"]["username"], "admin")
        self.assertEqual(body["user"]["role"], "ADMIN")
        self.assertNotIn("password", response.text.lower())
        self.assertNotIn("password_hash", response.text.lower())

    def test_login_wrong_password_fails(self):
        response = self.login(password="wrong-password")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("password_hash", response.text.lower())

    def test_login_inactive_user_fails(self):
        response = self.login("inactive", "inactive-password")

        self.assertEqual(response.status_code, 401)

    def test_protected_endpoint_requires_authentication(self):
        response = self.client.get("/api/admin/dashboard")

        self.assertEqual(response.status_code, 401)

    def test_invalid_token_is_rejected(self):
        response = self.client.get("/api/admin/dashboard", headers={"Authorization": "Bearer not-a-token"})

        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected(self):
        settings.auth_token_expire_seconds = -1
        response = self.login()
        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]

        response = self.client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)

    def test_logout_revokes_token(self):
        headers = self.auth_headers()

        self.assertEqual(self.client.get("/api/admin/dashboard", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 204)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=headers).status_code, 401)

    def test_admin_role_can_access_admin_endpoint(self):
        response = self.client.get("/api/admin/system", headers=self.auth_headers("admin", "admin-password"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permission"], "admin")

    def test_wrong_role_is_forbidden(self):
        response = self.client.get("/api/admin/receive-work", headers=self.auth_headers("handler", "handler-password"))

        self.assertEqual(response.status_code, 403)

    def test_receiver_role_can_access_receiver_endpoint(self):
        response = self.client.get("/api/admin/receive-work", headers=self.auth_headers("receiver", "receiver-password"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permission"], "receive")

    def test_handler_role_can_access_handler_endpoint(self):
        response = self.client.get("/api/admin/handle-work", headers=self.auth_headers("handler", "handler-password"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permission"], "handle")


if __name__ == "__main__":
    unittest.main()
