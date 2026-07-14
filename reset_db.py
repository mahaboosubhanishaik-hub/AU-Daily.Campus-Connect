from app import app, db, Admin, AllowedStudent
from werkzeug.security import generate_password_hash
from sqlalchemy import text
import csv
import os
import sys

initial_admin_id = os.getenv("INITIAL_ADMIN_ID")
initial_admin_password = os.getenv("INITIAL_ADMIN_PASSWORD")
if not initial_admin_id or not initial_admin_password:
    sys.exit("Set INITIAL_ADMIN_ID and INITIAL_ADMIN_PASSWORD before running this destructive development reset.")
if len(initial_admin_password) < 12:
    sys.exit("INITIAL_ADMIN_PASSWORD must be at least 12 characters.")

with app.app_context():
    print("Dropping all tables...")
    
    # Create all required media directories
    media_path = os.path.join(app.root_path, 'static', 'media')
    resource_path = os.path.join(media_path, 'resources')
    os.makedirs(resource_path, exist_ok=True)
    print(f"Verified media directories exist at {resource_path}")

    # Disable FK checks to prevent locking issues during drop
    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0'))
    db.session.commit()
    db.drop_all()
    db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1'))
    db.session.commit()
    
    print("Creating all tables...")
    db.create_all()

    # Create the explicitly supplied admin account; never create a known default.
    if not Admin.query.filter_by(admin_id=initial_admin_id).first():
        initial_admin = Admin(
            admin_id=initial_admin_id,
            password=generate_password_hash(initial_admin_password)
        )
        db.session.add(initial_admin)
        db.session.commit()
        print("Initial admin created")

    print("Populating allowed student IDs...")
    # =================================================================
    # Add your department's student registration numbers here
    # =================================================================
    allowed_ids = []
    
    # Look for allowed_students.csv in the application root
    csv_path = os.path.join(app.root_path, 'allowed_students.csv')
    
    if os.path.exists(csv_path):
        print(f"Found CSV file at {csv_path}. Importing IDs...")
        # Check if the path is a file, not a directory
        if not os.path.isfile(csv_path):
            print(f"\n[ERROR] The path '{csv_path}' is a directory, but it must be a CSV file.")
            print("Please delete the 'allowed_students.csv' folder and create a file with that name containing the student IDs.\n")
        else:
            # Check if it might be an xlsx file renamed to csv
            try:
                with open(csv_path, 'rb') as f:
                    if f.read(2) == b'PK':
                        print(f"\n[ERROR] '{csv_path}' appears to be an Excel (.xlsx) file saved with a .csv extension.")
                        print("Please open the file in Excel, choose 'Save As', and select 'CSV (Comma delimited) (*.csv)'.\n")
                        sys.exit(1)
            except OSError:
                pass

            encodings_to_try = ['utf-8-sig', 'cp1252', 'latin-1']
            file_read_successfully = False
            for encoding in encodings_to_try:
                try:
                    # Use newline='' as per csv module best practices
                    with open(csv_path, 'r', encoding=encoding, newline='') as f:
                        reader = csv.reader(f)
                        current_ids = []
                        row_count = 0
                        for row in reader:
                            row_count += 1
                            if row and len(row) > 0:
                                val = row[0].strip()
                                if val:
                                    potential_id = val.split()[0]
                                    if potential_id.lower() not in ['id', 'student', 'registration', 'reg', 'no']:
                                        current_ids.append(potential_id)
                        
                        if current_ids:
                            allowed_ids = list(set(current_ids)) # Deduplicate
                            print(f"Successfully read file with '{encoding}' encoding.")
                            file_read_successfully = True
                            break # Exit loop on first successful read
                        elif row_count > 0:
                            print(f"Read {row_count} rows with '{encoding}', but found no valid numeric IDs in the first column.")
                except UnicodeDecodeError:
                    print(f"Decoding with '{encoding}' failed. Trying next...")
                    continue
                except PermissionError:
                    print(f"\n[ERROR] Could not open '{csv_path}'. The file is currently open in another program (like Excel).")
                    print("Please close the file and try again.\n")
                    break
                except IOError as e:
                    print(f"\n[ERROR] A file system error occurred: {e}")
                    print("Please check file permissions.\n")
                    break
            
            if not file_read_successfully:
                print("\nWarning: Could not read student IDs from CSV. The file might be empty, have an unsupported encoding, or contain no valid IDs.\n")
    else:
        print("No CSV file found; no student IDs were imported.")

    for s_id in allowed_ids:
        if not AllowedStudent.query.filter_by(student_id=s_id).first():
            allowed_student = AllowedStudent(student_id=s_id)
            db.session.add(allowed_student)
    db.session.commit()
    print(f"{len(allowed_ids)} allowed student IDs have been added.")
    print("Database reset complete! You can now run app.py.")
