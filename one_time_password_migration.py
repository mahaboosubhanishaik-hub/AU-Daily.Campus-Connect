from app import app, db, Student
from werkzeug.security import generate_password_hash

def migrate_passwords():
    """
    A one-time script to find plaintext passwords in the database
    and hash them using Werkzeug's security helpers.
    """
    with app.app_context():
        students_to_migrate = Student.query.all()
        migrated_count = 0
        print(f"Found {len(students_to_migrate)} students to check for migration.")

        for student in students_to_migrate:
            # Werkzeug password hashes start with a prefix like 'pbkdf2:sha256:'.
            # If the password doesn't have this, it's likely plaintext.
            if student.password and not student.password.startswith('pbkdf2:sha256:'):
                print(f"Migrating password for student ID: {student.student_id}...")
                student.password = generate_password_hash(student.password)
                migrated_count += 1
        
        if migrated_count > 0:
            db.session.commit()
            print(f"\nSuccessfully migrated {migrated_count} student passwords.")
        else:
            print("\nNo passwords needed migration. All seem to be hashed already.")

if __name__ == "__main__":
    migrate_passwords()