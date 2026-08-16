"""Safely add new student IDs from the CSV to the database.

This script is non-destructive. It reads the `allowed_students.csv` file and
adds any student IDs that are not already in the `allowed_student` table.
It will not remove any students or affect existing data.
"""
import csv
import os
import sys

from app import app, db, AllowedStudent


def get_allowed_ids_from_csv(path):
    """Read student IDs from the specified CSV file."""
    if not os.path.isfile(path):
        print(f"Error: The file '{path}' was not found.")
        return set()
    with open(path, encoding="utf-8-sig", newline="") as csv_file:
        return {
            row[0].strip() for row in csv.reader(csv_file) if row and row[0].strip()
        }


with app.app_context():
    csv_path = os.path.join(app.root_path, "allowed_students.csv")
    new_ids = get_allowed_ids_from_csv(csv_path)
    existing_ids = {s.student_id for s in AllowedStudent.query.all()}
    ids_to_add = new_ids - existing_ids

    if not ids_to_add:
        print("All student IDs from the CSV are already in the database. No updates needed.")
        sys.exit(0)

    for student_id in sorted(list(ids_to_add)):
        db.session.add(AllowedStudent(student_id=student_id))

    db.session.commit()
    print(f"Successfully added {len(ids_to_add)} new student IDs to the whitelist.")