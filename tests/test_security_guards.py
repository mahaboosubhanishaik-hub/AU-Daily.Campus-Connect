import importlib
import os
import sys
import unittest


class SecurityGuardTests(unittest.TestCase):
    def setUp(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        sys.path.insert(0, repo_root)

        import app as app_module
        self.app_module = importlib.reload(app_module)
        self.app = self.app_module.create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        with self.app.app_context():
            engine = self.app.extensions["sqlalchemy"].engine
        self.addCleanup(engine.dispose)

    def test_all_post_routes_are_csrf_protected(self):
        unprotected = []
        for rule in self.app.url_map.iter_rules():
            if "POST" not in rule.methods:
                continue
            view = self.app.view_functions[rule.endpoint]
            if not getattr(view, "_csrf_protected", False):
                unprotected.append(f"{rule.endpoint}: {rule.rule}")

        self.assertEqual(unprotected, [])


if __name__ == "__main__":
    unittest.main()
