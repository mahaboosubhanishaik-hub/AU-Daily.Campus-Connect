"""Create a brand-new production schema without dropping existing data.

Run this once only for an empty database, then use ``flask db upgrade`` for all
future releases. It deliberately refuses databases that already contain app
tables, so it cannot accidentally replace a live schema.
"""
import csv
import os
import sys

from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

from app import app, db, Admin, AllowedStudent


HEAD_REVISION = "a3e4f5a6b7c8"
admin_id = os.getenv("INITIAL_ADMIN_ID")
admin_password = os.getenv("INITIAL_ADMIN_PASSWORD")
if not admin_id or not admin_password or len(admin_password) < 12:
    sys.exit("Set INITIAL_ADMIN_ID and a 12+ character INITIAL_ADMIN_PASSWORD before bootstrapping.")


def allowed_ids_from_csv(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as csv_file:
        return {
            row[0].strip().split()[0]
            for row in csv.reader(csv_file)
            if row and row[0].strip() and row[0].strip().split()[0].lower() not in {"id", "student", "registration", "reg", "no"}
        }


with app.app_context():
    tables = set(inspect(db.engine).get_table_names()) - {"alembic_version"}
    if tables:
        sys.exit("Database is not empty. Refusing to bootstrap an existing schema; run `flask db upgrade` instead.")

    db.create_all()
    db.session.add(Admin(admin_id=admin_id, password=generate_password_hash(admin_password)))
    for student_id in allowed_ids_from_csv(os.path.join(app.root_path, "allowed_students.csv")):
        db.session.add(AllowedStudent(student_id=student_id))
    db.session.commit()

    # The schema is built from the current models, so mark it at the current
    # Alembic head. Later releases use ordinary migrations.
    db.session.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
    db.session.execute(text("DELETE FROM alembic_version"))
    db.session.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": HEAD_REVISION})
    db.session.commit()
    print("Production database bootstrapped successfully.")
