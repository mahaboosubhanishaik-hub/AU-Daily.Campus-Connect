from app import app, db, AllowedStudent
import csv
import os
import sys

def update_ids():
    with app.app_context():
        print("--- Update Allowed Students Script ---")
        print("This script adds new IDs from 'allowed_students.csv' to the database.")
        print("It does NOT delete existing data.\n")

        allowed_ids = []
        csv_path = os.path.join(app.root_path, 'allowed_students.csv')
        
        if os.path.exists(csv_path):
            print(f"Reading {csv_path}...")
            
            if not os.path.isfile(csv_path):
                print(f"[ERROR] '{csv_path}' is a directory. Please replace it with a CSV file.")
                sys.exit(1)
                
            # Check for Excel file disguised as CSV
            try:
                with open(csv_path, 'rb') as f:
                    if f.read(2) == b'PK':
                        print(f"[ERROR] '{csv_path}' is an Excel .xlsx file. Save it as CSV.")
                        sys.exit(1)
            except OSError:
                pass

            encodings = ['utf-8-sig', 'cp1252', 'latin-1']
            success = False
            
            for encoding in encodings:
                try:
                    with open(csv_path, 'r', encoding=encoding, newline='') as f:
                        reader = csv.reader(f)
                        temp_ids = []
                        for row in reader:
                            if row and len(row) > 0:
                                # Extract first word (ID) from the first column
                                # This handles "321... Name" formats
                                val = row[0].strip()
                                if val:
                                    potential_id = val.split()[0]
                                    # Support alphanumeric IDs while skipping common header words
                                    if potential_id.lower() not in ['id', 'student', 'registration', 'reg', 'no', 'number']:
                                        temp_ids.append(potential_id)
                        
                        if temp_ids:
                            allowed_ids = temp_ids
                            print(f"Successfully read {len(allowed_ids)} IDs using {encoding}.")
                            success = True
                            break
                except (UnicodeDecodeError, PermissionError, IOError):
                    continue
            
            if not success:
                print("[ERROR] Could not read IDs from CSV. Check format/encoding.")
                sys.exit(1)
                
        else:
            print(f"[ERROR] {csv_path} not found.")
            sys.exit(1)

        print(f"Processing {len(allowed_ids)} IDs...")
        
        added_count = 0
        # Deduplicate the list to avoid IntegrityErrors if the CSV has duplicate new IDs
        unique_ids = list(set(allowed_ids))
        
        for s_id in unique_ids:
            if not AllowedStudent.query.filter_by(student_id=s_id).first():
                db.session.add(AllowedStudent(student_id=s_id))
                added_count += 1
                
        db.session.commit()
        
        print(f"\nSuccess! {added_count} new IDs added.")
        print(f"Total allowed IDs in database: {AllowedStudent.query.count()}")

if __name__ == "__main__":
    update_ids()