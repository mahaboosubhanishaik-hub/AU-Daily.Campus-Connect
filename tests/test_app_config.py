import importlib
import os
import sys
import unittest
from unittest.mock import patch


class AppConfigTests(unittest.TestCase):
    def test_create_app_uses_sqlite_in_development_when_database_url_missing(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        sys.path.insert(0, repo_root)

        with patch.dict(
            os.environ,
            {
                "APP_ENV": "development",
                "SECRET_KEY": "dev-secret",
                "PUBLIC_BASE_URL": "https://example.com",
            },
            clear=False,
        ):
            os.environ.pop("DATABASE_URL", None)
            os.environ.pop("SQLALCHEMY_DATABASE_URI", None)

            import dotenv
            with patch.object(dotenv, "load_dotenv", return_value=False):
                import app as app_module
                app_module = importlib.reload(app_module)

                created_app = app_module.create_app()
                with created_app.app_context():
                    engine = created_app.extensions["sqlalchemy"].engine
                self.addCleanup(engine.dispose)
                self.assertTrue(
                    created_app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///"),
                    created_app.config["SQLALCHEMY_DATABASE_URI"],
                )


if __name__ == "__main__":
    unittest.main()
