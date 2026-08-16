import importlib
import os
import sys
import unittest
from datetime import timedelta
from unittest.mock import PropertyMock, patch

from sqlalchemy.exc import SQLAlchemyError


class LoginFlowTests(unittest.TestCase):
    def setUp(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        sys.path.insert(0, repo_root)

        import app as app_module
        self.app_module = importlib.reload(app_module)
        self.app = self.app_module.create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

        self.ctx = self.app.app_context()
        self.ctx.push()
        self.app_module.db.drop_all()
        self.app_module.db.create_all()

        self.addCleanup(self.app.extensions["sqlalchemy"].engine.dispose)
        self.addCleanup(self.ctx.pop)
        self.addCleanup(self.app_module.db.session.remove)
        self.addCleanup(self.app_module.db.drop_all)

    def _create_admin(self, admin_id="12345678", password="@admin"):
        admin = self.app_module.Admin(
            admin_id=admin_id,
            password=self.app_module.generate_password_hash(password),
        )
        self.app_module.db.session.add(admin)
        self.app_module.db.session.commit()
        return admin

    def _create_student(self, student_id="324207360124", email="student@example.com", password="TestPass123"):
        student = self.app_module.Student(
            student_id=student_id,
            name="Test Student",
            department="Computer Science & Systems Engineering",
            graduation_year=2026,
            email=email,
            password=self.app_module.generate_password_hash(password),
            is_verified=True,
        )
        self.app_module.db.session.add(student)
        self.app_module.db.session.commit()
        return student

    def test_admin_login_post_redirects_for_valid_admin(self):
        self._create_admin()

        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = 'test-csrf-token'

        with patch.object(self.app_module, "login_is_rate_limited", return_value=False), \
             patch.object(self.app_module, "clear_login_rate_limit"), \
             patch.object(self.app_module, "record_failed_login"), \
             patch.object(self.app_module, "verify_password_and_upgrade", return_value=True):
            response = self.client.post(
                "/admin/login",
                data={
                    "admin_id": "12345678",
                    "password": "@admin",
                    "csrf_token": "test-csrf-token",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "http://localhost/admin/dashboard")

    def test_student_login_accepts_registered_email(self):
        self._create_student()

        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = 'test-csrf-token'

        response = self.client.post(
            "/student/login",
            data={
                "student_id": "student@example.com",
                "password": "TestPass123",
                "csrf_token": "test-csrf-token",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "http://localhost/")

    def test_reset_password_requires_matching_confirmation(self):
        student = self._create_student()
        token = self.app_module.password_reset_serializer.dumps(
            student.email,
            salt="student-password-reset",
        )

        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = 'test-csrf-token'

        response = self.client.post(
            f"/student/reset-password/{token}",
            data={
                "password": "NewPass1234",
                "confirm_password": "Different1234",
                "csrf_token": "test-csrf-token",
            },
            follow_redirects=False,
        )

        self.app_module.db.session.refresh(student)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            self.app_module.check_password_hash(student.password, "TestPass123")
        )

    def test_recovery_request_updates_existing_pending_request(self):
        self._create_student()

        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = 'test-csrf-token'

        auth_module = sys.modules["auth"]
        with patch.object(auth_module, "send_admin_alert"):
            for email in ("first@example.com", "second@example.com"):
                response = self.client.post(
                    "/student/request-admin-recovery",
                    data={
                        "student_id": "324207360124",
                        "recovery_email": email,
                        "contact_note": "Office visit",
                        "csrf_token": "test-csrf-token",
                    },
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 302)

        requests = self.app_module.RecoveryRequest.query.all()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].recovery_email, "second@example.com")

    def test_rate_limit_attempts_fall_back_when_db_is_unavailable(self):
        with patch.object(
            self.app_module.AuthRateLimit,
            "query",
            new_callable=PropertyMock,
        ) as query_mock:
            query_mock.return_value.filter_by.side_effect = SQLAlchemyError("db unavailable")
            self.app_module.record_rate_limit_attempt("fallback:test", timedelta(minutes=5))

    def test_clear_login_rate_limit_falls_back_when_db_is_unavailable(self):
        with patch.object(
            self.app_module.AuthRateLimit,
            "query",
            new_callable=PropertyMock,
        ) as query_mock:
            query_mock.return_value.filter_by.side_effect = SQLAlchemyError("db unavailable")
            self.app_module.clear_login_rate_limit("fallback:test")


if __name__ == "__main__":
    unittest.main()
