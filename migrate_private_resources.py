"""Move existing public resource files out of static/ after a backup.

Run once during deployment. It only moves files referenced by Resource rows and
leaves unknown files untouched for manual review.
"""
import os
import shutil

from app import app, db, Resource


with app.app_context():
    source = app.config["LEGACY_RESOURCE_FOLDER"]
    destination = app.config["RESOURCE_FOLDER"]
    os.makedirs(destination, exist_ok=True)
    moved = 0
    for resource in Resource.query.all():
        filename = os.path.basename(resource.file_path)
        old_path = os.path.join(source, filename)
        new_path = os.path.join(destination, filename)
        if os.path.isfile(old_path) and not os.path.exists(new_path):
            shutil.move(old_path, new_path)
            moved += 1
    print(f"Moved {moved} resource file(s) into protected storage.")
