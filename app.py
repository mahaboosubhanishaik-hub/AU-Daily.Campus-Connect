from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, abort, send_from_directory, current_app, Blueprint, g, stream_with_context
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect, or_, func
from sqlalchemy.orm import selectinload
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import csv
import io
import re
import uuid
import random
import string
import zipfile
import json
import importlib
import warnings
import click
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from datetime import datetime, timedelta
from markupsafe import escape
import calendar
import hmac
import hashlib
import secrets
import sys, time
from functools import wraps
from urllib.parse import urlparse, urljoin
from PyPDF2 import PdfReader
try:
    from pydantic.warnings import ArbitraryTypeWarning
except ImportError:
    ArbitraryTypeWarning = Warning

warnings.filterwarnings(
    "ignore",
    message=r".*<built-in function any> is not a Python type.*",
    category=ArbitraryTypeWarning,
    module=r"pydantic\._internal\._generate_schema",
)

try:
    from google import genai
except ImportError:
    # AI is optional; administrative tools and account recovery must still run
    # when the Gemini SDK is not installed.
    genai = None
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# Ensure `from app import ...` resolves to this running module when the file is
# executed as a script. That prevents a second import of `app.py` during
# `auth.py` initialization.
sys.modules.setdefault('app', sys.modules[__name__])

db = SQLAlchemy()
mail = Mail()
migrate = Migrate()
password_reset_serializer = None # Will be initialized in the app factory


def local_sqlite_url(app):
    db_path = os.path.abspath(os.path.join(app.root_path, "app.db"))
    return f"sqlite:///{db_path.replace(os.sep, '/')}"


def development_database_url(app, db_url):
    """Keep development fast and offline-friendly unless remote DB is explicitly requested."""
    if is_production or not db_url or db_url.startswith("sqlite"):
        return db_url

    running_on_render = os.getenv("RENDER", "").lower() in {"1", "true", "yes"}
    if running_on_render:
        return db_url

    fallback_enabled = os.getenv("LOCAL_DB_FALLBACK", "false").lower() in {"1", "true", "yes"}
    use_remote_database = os.getenv("USE_REMOTE_DATABASE", "").lower() in {"1", "true", "yes"}
    if not fallback_enabled or use_remote_database:
        return db_url

    fallback_url = local_sqlite_url(app)
    app.logger.debug(
        "Using local SQLite for development. Set USE_REMOTE_DATABASE=true to use DATABASE_URL."
    )
    return fallback_url


def seed_development_accounts(app):
    """Create local-only starter accounts so development login is not blocked by an empty DB."""
    if is_production or app.config.get("TESTING"):
        return
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///"):
        return
    if os.getenv("DEV_BOOTSTRAP_ACCOUNTS", "true").lower() not in {"1", "true", "yes"}:
        return

    try:
        with app.app_context():
            _seed_development_accounts()
    except Exception:
        app.logger.exception("Failed to create local development login accounts")


def _seed_development_accounts():
    created = []
    admin_id = os.getenv("INITIAL_ADMIN_ID", "admin")
    admin_password = os.getenv("INITIAL_ADMIN_PASSWORD", "Admin@12345")
    if Admin.query.count() == 0:
        db.session.add(Admin(
            admin_id=admin_id,
            password=generate_password_hash(admin_password),
        ))
        created.append(f"admin '{admin_id}'")

    if Student.query.count() == 0:
        dev_student_id = os.getenv("DEV_STUDENT_ID")
        allowed_student = None
        if dev_student_id:
            allowed_student = AllowedStudent.query.filter_by(student_id=dev_student_id).first()
        if not allowed_student:
            allowed_student = AllowedStudent.query.order_by(AllowedStudent.student_id).first()

        if allowed_student:
            student_id = allowed_student.student_id
            db.session.add(Student(
                student_id=student_id,
                name=os.getenv("DEV_STUDENT_NAME", "Development Student"),
                department=os.getenv("DEV_STUDENT_DEPARTMENT", "Computer Science & Systems Engineering"),
                graduation_year=int(os.getenv("DEV_STUDENT_GRADUATION_YEAR", "2026")),
                email=os.getenv("DEV_STUDENT_EMAIL", "student@example.com"),
                phone=os.getenv("DEV_STUDENT_PHONE", "9999999999"),
                password=generate_password_hash(os.getenv("DEV_STUDENT_PASSWORD", "Student@12345")),
                is_verified=True,
            ))
            created.append(f"student '{student_id}'")

    if created:
        db.session.commit()
        current_app.logger.warning(
            "Created local development login accounts: %s. Set DEV_BOOTSTRAP_ACCOUNTS=false to disable.",
            ", ".join(created),
        )
    else:
        db.session.rollback()

    return

    try:
        created = []
        admin_id = os.getenv("INITIAL_ADMIN_ID", "admin")
        admin_password = os.getenv("INITIAL_ADMIN_PASSWORD", "Admin@12345")
        if Admin.query.count() == 0:
            db.session.add(Admin(
                admin_id=admin_id,
                password=generate_password_hash(admin_password),
            ))
            created.append(f"admin '{admin_id}'")

        if Student.query.count() == 0:
            dev_student_id = os.getenv("DEV_STUDENT_ID")
            allowed_student = None
            if dev_student_id:
                allowed_student = AllowedStudent.query.filter_by(student_id=dev_student_id).first()
            if not allowed_student:
                allowed_student = AllowedStudent.query.order_by(AllowedStudent.student_id).first()

            if allowed_student:
                student_id = allowed_student.student_id
                db.session.add(Student(
                    student_id=student_id,
                    name=os.getenv("DEV_STUDENT_NAME", "Development Student"),
                    department=os.getenv("DEV_STUDENT_DEPARTMENT", "Computer Science & Systems Engineering"),
                    graduation_year=int(os.getenv("DEV_STUDENT_GRADUATION_YEAR", "2026")),
                    email=os.getenv("DEV_STUDENT_EMAIL", "student@example.com"),
                    phone=os.getenv("DEV_STUDENT_PHONE", "9999999999"),
                    password=generate_password_hash(os.getenv("DEV_STUDENT_PASSWORD", "Student@12345")),
                    is_verified=True,
                ))
                created.append(f"student '{student_id}'")

        if created:
            db.session.commit()
            app.logger.warning(
                "Created local development login accounts: %s. Set DEV_BOOTSTRAP_ACCOUNTS=false to disable.",
                ", ".join(created),
            )
    except Exception:
        db.session.rollback()
        app.logger.exception("Failed to create local development login accounts")


def passthrough_wsgi_app(wsgi_app):
    """Keep the default Flask WSGI chain explicit and stable across launch modes."""
    def wrapped(environ, start_response):
        return wsgi_app(environ, start_response)

    return wrapped

is_production = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower() == "production"

# # ==========================
# GEMINI API CONFIGURATION
# ==========================

# Support both environment variable names
GEMINI_API_KEY = (
    os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
)

gemini_client = None

if GEMINI_API_KEY and not genai:
    print("WARNING: google-genai package is not installed. AI features will be disabled.")
    GEMINI_API_KEY = None


def get_gemini_client():
    """Initialize Gemini only when an AI feature actually needs it."""
    global gemini_client, GEMINI_API_KEY
    if gemini_client or not genai or not GEMINI_API_KEY:
        return gemini_client

    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        current_app.logger.info("Gemini AI initialized successfully.")
    except Exception as e:
        current_app.logger.warning(
            "Gemini API could not be initialized. AI features will be disabled. Error: %s",
            e,
        )
        GEMINI_API_KEY = None
    return gemini_client


def clear_nav_count_cache():
    session.pop("nav_counts_cache", None)


def login_rate_limit_key(account_hint):
    """Limit repeated guesses by both source address and account identifier."""
    return f"{request.remote_addr or 'unknown'}:{(account_hint or '').strip().lower()[:120]}"


def login_is_rate_limited(key):
    return rate_limit_reached(f"login:{key}", limit=10, window=timedelta(minutes=15))


def record_failed_login(key):
    record_rate_limit_attempt(f"login:{key}", window=timedelta(minutes=15))


def password_reset_is_rate_limited():
    key = f"password-reset:{request.remote_addr or 'unknown'}"
    if rate_limit_reached(key, limit=5, window=timedelta(hours=1)):
        return True
    record_rate_limit_attempt(key, window=timedelta(hours=1))
    return False


def clear_login_rate_limit(key):
    try:
        row = AuthRateLimit.query.filter_by(key=f"login:{key}").first()
        if row:
            db.session.delete(row)
            db.session.commit()
    except Exception:
        db.session.rollback()
        return


def rate_limit_reached(key, limit, window):
    try:
        row = AuthRateLimit.query.filter_by(key=key).first()
    except Exception:
        return False
    return bool(row and row.window_started_at > datetime.now() - window and row.attempt_count >= limit)


def record_rate_limit_attempt(key, window):
    now = datetime.now()
    try:
        row = AuthRateLimit.query.filter_by(key=key).first()
        if not row:
            row = AuthRateLimit(key=key, window_started_at=now, attempt_count=1)
            db.session.add(row)
        elif row.window_started_at <= now - window:
            row.window_started_at, row.attempt_count = now, 1
        else:
            row.attempt_count += 1
        db.session.commit()
    except Exception:
        # The login flow should remain usable even if the rate-limit table is temporarily unavailable.
        return


def import_default_allowed_students(app):
    """Import IDs from allowed_students.csv once at startup, logging only meaningful outcomes."""
    csv_path = os.path.join(app.root_path, 'allowed_students.csv')
    if not os.path.exists(csv_path):
        return

    with app.app_context():
        try:
            engine_url = db.engine.url
            is_local_sqlite = engine_url.drivername.startswith("sqlite")
            auto_import_remote = os.getenv("AUTO_IMPORT_ALLOWED_STUDENTS", "").lower() in {"1", "true", "yes"}
            if not is_local_sqlite and not auto_import_remote:
                app.logger.debug(
                    "Skipping allowed_students.csv startup import for remote database. "
                    "Set AUTO_IMPORT_ALLOWED_STUDENTS=true to enable it."
                )
                return

            if (
                is_local_sqlite
                and engine_url.database
                and engine_url.database != ":memory:"
                and not os.path.exists(engine_url.database)
            ):
                return

            if not inspect(db.engine).has_table(AllowedStudent.__tablename__):
                return

            existing_ids = {s.student_id for s in AllowedStudent.query.all()}
            new_ids = set()
            encodings = ['utf-8-sig', 'cp1252', 'latin-1']

            for encoding in encodings:
                try:
                    with open(csv_path, 'r', encoding=encoding, newline='') as f:
                        reader = csv.reader(f)
                        ids_from_this_encoding = set()
                        for row in reader:
                            if not row:
                                continue
                            value = row[0].strip()
                            if not value:
                                continue
                            potential_id = value.split()[0]
                            if potential_id.lower() not in {'id', 'student', 'registration', 'reg', 'no'}:
                                ids_from_this_encoding.add(potential_id)
                    if ids_from_this_encoding:
                        new_ids = ids_from_this_encoding
                        break
                except UnicodeDecodeError:
                    continue

            ids_to_add = new_ids - existing_ids
            if not ids_to_add:
                return

            for student_id in sorted(ids_to_add):
                db.session.add(AllowedStudent(student_id=student_id))
            db.session.commit()
            app.logger.info('Imported %d allowed student IDs from %s', len(ids_to_add), csv_path)
        except Exception:
            db.session.rollback()
            app.logger.exception('Failed to import allowed_students.csv')


def import_allowed_students_from_csv(csv_path):
    """Import allowed student IDs from a CSV path and return the number added."""
    existing_ids = {s.student_id for s in AllowedStudent.query.all()}
    new_ids = set()
    encodings = ['utf-8-sig', 'cp1252', 'latin-1']

    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding, newline='') as f:
                reader = csv.reader(f)
                ids_from_this_encoding = {
                    normalize_allowed_student_id(row[0])
                    for row in reader
                    if row
                }
            ids_from_this_encoding.discard("")
            if ids_from_this_encoding:
                new_ids = ids_from_this_encoding
                break
        except UnicodeDecodeError:
            continue

    ids_to_add = new_ids - existing_ids
    for student_id in sorted(ids_to_add):
        db.session.add(AllowedStudent(student_id=student_id))
    return len(ids_to_add)


def register_maintenance_commands(app):
    @app.cli.command("repair-logins")
    @click.option("--seed-allowed/--no-seed-allowed", default=True, show_default=True, help="Import IDs from allowed_students.csv.")
    @click.option("--admin-id", envvar="REPAIR_ADMIN_ID", help="Admin ID to create or reset.")
    @click.option("--admin-password", envvar="REPAIR_ADMIN_PASSWORD", help="New admin password.")
    @click.option("--student-id", envvar="REPAIR_STUDENT_ID", help="Student ID to create or reset.")
    @click.option("--student-password", envvar="REPAIR_STUDENT_PASSWORD", help="New student password.")
    @click.option("--student-email", envvar="REPAIR_STUDENT_EMAIL", help="Email for a created student.")
    @click.option("--student-name", envvar="REPAIR_STUDENT_NAME", default="AU Daily Student", show_default=True)
    @click.option("--student-department", envvar="REPAIR_STUDENT_DEPARTMENT", default="Computer Science & Systems Engineering", show_default=True)
    @click.option("--student-graduation-year", envvar="REPAIR_STUDENT_GRADUATION_YEAR", default=2026, show_default=True, type=int)
    def repair_logins(seed_allowed, admin_id, admin_password, student_id, student_password, student_email, student_name, student_department, student_graduation_year):
        """Seed/reset production login records without dropping existing data."""
        added_allowed = 0
        changed = []

        if seed_allowed:
            csv_path = os.path.join(app.root_path, 'allowed_students.csv')
            if os.path.exists(csv_path):
                added_allowed = import_allowed_students_from_csv(csv_path)

        if admin_id or admin_password:
            if not admin_id or not admin_password:
                raise click.UsageError("Provide both --admin-id and --admin-password.")
            if len(admin_password) < 10:
                raise click.UsageError("Admin password must be at least 10 characters.")
            admin = Admin.query.filter_by(admin_id=admin_id).first()
            if not admin:
                admin = Admin(admin_id=admin_id)
                db.session.add(admin)
                changed.append(f"created admin {admin_id}")
            else:
                changed.append(f"reset admin {admin_id}")
            admin.password = generate_password_hash(admin_password)

        if student_id or student_password:
            if not student_id or not student_password:
                raise click.UsageError("Provide both --student-id and --student-password.")
            if len(student_password) < 10:
                raise click.UsageError("Student password must be at least 10 characters.")

            allowed = AllowedStudent.query.filter_by(student_id=student_id).first()
            if not allowed:
                db.session.add(AllowedStudent(student_id=student_id))

            student = Student.query.filter_by(student_id=student_id).first()
            if not student:
                if not student_email:
                    raise click.UsageError("Provide --student-email when creating a new student.")
                student = Student(
                    student_id=student_id,
                    name=student_name,
                    department=student_department,
                    graduation_year=student_graduation_year,
                    email=student_email.strip().lower(),
                    is_verified=True,
                )
                db.session.add(student)
                changed.append(f"created student {student_id}")
            else:
                changed.append(f"reset student {student_id}")
                if student_email:
                    student.email = student_email.strip().lower()
                student.is_verified = True
            student.password = generate_password_hash(student_password)

        AuthRateLimit.query.filter(AuthRateLimit.key.like("login:%")).delete(synchronize_session=False)
        db.session.commit()

        click.echo(f"Imported {added_allowed} allowed student IDs.")
        click.echo("Login repair complete: " + (", ".join(changed) if changed else "no account changes"))


def log_database_login_summary(app):
    """Log a safe startup summary so deployment DB mismatches are obvious."""
    should_log = (
        os.getenv("LOG_DATABASE_SUMMARY", "").lower() in {"1", "true", "yes"}
        or os.getenv("RENDER", "").lower() in {"1", "true", "yes"}
    )
    if not should_log:
        return

    try:
        with app.app_context():
            rendered_url = db.engine.url.render_as_string(hide_password=True)
            admin_count = Admin.query.count() if inspect(db.engine).has_table(Admin.__tablename__) else "missing-table"
            student_count = Student.query.count() if inspect(db.engine).has_table(Student.__tablename__) else "missing-table"
            allowed_count = AllowedStudent.query.count() if inspect(db.engine).has_table(AllowedStudent.__tablename__) else "missing-table"
            app.logger.warning(
                "Database login summary: url=%s admins=%s students=%s allowed_students=%s",
                rendered_url,
                admin_count,
                student_count,
                allowed_count,
            )
    except Exception:
        db.session.rollback()
        app.logger.exception("Database login summary failed")


def normalize_allowed_student_id(value):
    """Extract a clean student ID from manual input or the first CSV column."""
    if not value:
        return ""
    student_id = str(value).strip().split()[0]
    if student_id.lower() in {'id', 'student', 'registration', 'reg', 'no'}:
        return ""
    return student_id


def csrf_token():
    """Return a session-bound token for destructive browser actions."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


def require_csrf(view):
    """Reject cross-site form posts before a destructive action is performed."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method in {'GET', 'HEAD', 'OPTIONS'}:
            return view(*args, **kwargs)
        submitted_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not submitted_token or not hmac.compare_digest(submitted_token, csrf_token()):
            abort(400, description='Invalid or missing security token.')
        return view(*args, **kwargs)
    wrapped._csrf_protected = True
    return wrapped


IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic'}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def allowed_media_file(filename):
    """Media fields must not accept documents merely because they are allowed elsewhere."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)


def upload_content_is_safe(file_storage):
    """Reject files whose bytes do not match their claimed safe type.

    This is intentionally a lightweight first line of defense, not a substitute
    for server-side malware scanning in production.
    """
    filename = secure_filename(file_storage.filename or '')
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in current_app.config['ALLOWED_EXTENSIONS']:
        return False
    try:
        stream = file_storage.stream
        position = stream.tell()
        header = stream.read(8192)
        stream.seek(position)
    except (AttributeError, OSError):
        return False
    signatures = {
        'png': (b'\x89PNG\r\n\x1a\n',),
        'jpg': (b'\xff\xd8\xff',), 'jpeg': (b'\xff\xd8\xff',),
        'gif': (b'GIF87a', b'GIF89a'),
        'pdf': (b'%PDF-',),
        'doc': (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
        'ppt': (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
        'docx': (b'PK\x03\x04',), 'pptx': (b'PK\x03\x04',),
        'webm': (b'\x1a\x45\xdf\xa3',),
    }
    if ext in signatures:
        return header.startswith(signatures[ext])
    if ext == 'webp':
        return header.startswith(b'RIFF') and header[8:12] == b'WEBP'
    if ext == 'avi':
        return header.startswith(b'RIFF') and header[8:12] == b'AVI '
    if ext in {'mp4', 'mov', 'heic'}:
        # ISO base media files advertise their type in the first bytes.
        return len(header) >= 12 and header[4:8] == b'ftyp'
    if ext == 'txt':
        return b'\x00' not in header
    return False


def safe_redirect_target(fallback):
    """Only redirect back to local pages; never trust a supplied external URL."""
    referrer = request.referrer
    if not referrer:
        return fallback
    target = urlparse(urljoin(request.host_url, referrer))
    if target.scheme in {'http', 'https'} and target.netloc == request.host:
        return target.geturl()
    return fallback


def valid_password(password):
    """Use a minimum length plus mixed character classes for account passwords."""
    return len(password or '') >= 10 and bool(re.search(r'[A-Za-z]', password)) and bool(re.search(r'\d', password))


def valid_external_url(value):
    if not value:
        return True
    parsed = urlparse(value.strip())
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def time_ago(value):
    if not value:
        return ''
    if isinstance(value, str):
        return value

    now = datetime.now(value.tzinfo) if getattr(value, 'tzinfo', None) else datetime.now()
    delta = now - value
    seconds = int(delta.total_seconds())

    if seconds < 0:
        seconds = 0

    if seconds < 60:
        return 'just now' if seconds < 5 else f'{seconds} seconds ago'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes} minute{"s" if minutes != 1 else ""} ago'
    hours = minutes // 60
    if hours < 24:
        return f'{hours} hour{"s" if hours != 1 else ""} ago'
    days = hours // 24
    if days < 7:
        return f'{days} day{"s" if days != 1 else ""} ago'
    weeks = days // 7
    if weeks < 5:
        return f'{weeks} week{"s" if weeks != 1 else ""} ago'
    months = days // 30
    if months < 12:
        return f'{months} month{"s" if months != 1 else ""} ago'
    years = days // 365
    return f'{years} year{"s" if years != 1 else ""} ago'


def public_url_for(endpoint, **values):
    """Build security-sensitive public links from the configured canonical origin."""
    path = url_for(endpoint, **values)
    if current_app.config.get('PUBLIC_BASE_URL'):
        return urljoin(f"{current_app.config['PUBLIC_BASE_URL']}/", path.lstrip('/'))
    return url_for(endpoint, _external=True, **values)


def remove_uploaded_media(filename):
    """Delete a uniquely-named public upload when its database record is removed."""
    if not filename:
        return
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], os.path.basename(filename))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        current_app.logger.warning('Could not remove uploaded media: %s', filename)


def verify_password_and_upgrade(account, submitted_password):
    """Verify current hashes and transparently upgrade passwords from legacy data."""
    stored_password = (account.password or "").strip()
    if (
        len(stored_password) >= 3
        and stored_password[:2] in {"b'", 'b"'}
        and stored_password[-1] == stored_password[1]
    ):
        stored_password = stored_password[2:-1]

    # If there is no password stored in the database, verification must fail.
    if not stored_password:
        return False

    try:
        if check_password_hash(stored_password, submitted_password):
            return True
    except (TypeError, ValueError):
        # Older database imports may contain a plain-text password.  Accept it
        # once and immediately replace it with a secure hash.
        pass

    if stored_password and hmac.compare_digest(stored_password, submitted_password):
        account.password = generate_password_hash(submitted_password)
        db.session.commit()
        return True

    legacy_hashes = {
        hashlib.md5(submitted_password.encode("utf-8")).hexdigest(),
        hashlib.sha1(submitted_password.encode("utf-8")).hexdigest(),
        hashlib.sha256(submitted_password.encode("utf-8")).hexdigest(),
    }
    if stored_password.lower() in legacy_hashes:
        account.password = generate_password_hash(submitted_password)
        db.session.commit()
        return True
    return False


def env_login_password_matches(user_model, submitted_id, submitted_password):
    """Allow a deployment-only credential fallback without changing database rows."""
    if user_model is Admin:
        env_id = os.getenv("ADMIN_LOGIN_ID") or os.getenv("INITIAL_ADMIN_ID")
        env_password = os.getenv("ADMIN_LOGIN_PASSWORD") or os.getenv("INITIAL_ADMIN_PASSWORD")
    elif user_model is Student:
        env_id = os.getenv("STUDENT_LOGIN_ID") or os.getenv("DEV_STUDENT_ID")
        env_password = os.getenv("STUDENT_LOGIN_PASSWORD") or os.getenv("DEV_STUDENT_PASSWORD")
    else:
        return False

    if not env_id or not env_password:
        return False

    return (
        hmac.compare_digest(submitted_id.strip().lower(), env_id.strip().lower())
        and hmac.compare_digest(submitted_password, env_password)
    )


def ensure_env_login_account(user_model, submitted_id, submitted_password):
    """Create or repair the env-configured login account after env credentials match."""
    if not env_login_password_matches(user_model, submitted_id, submitted_password):
        return None

    if user_model is Admin:
        admin = Admin.query.filter(
            func.lower(func.trim(Admin.admin_id)) == submitted_id.strip().lower()
        ).first()
        if not admin:
            admin = Admin(admin_id=submitted_id.strip())
            db.session.add(admin)
        admin.password = generate_password_hash(submitted_password)
        db.session.flush()
        return admin

    if user_model is Student:
        student = Student.query.filter(
            func.lower(func.trim(Student.student_id)) == submitted_id.strip().lower()
        ).first()
        if student:
            student.password = generate_password_hash(submitted_password)
            student.is_verified = True
            db.session.flush()
        return student

    return None

# AVAILABLE DEPARTMENTS


def _handle_login_attempt(user_model, user_id_attr, submitted_id, submitted_password, success_redirect_endpoint, failure_message, template_name, csrf_token_func, lookup_attrs=None):
    """
    Handles a generic login attempt for both students and admins.
    """
    submitted_id = (submitted_id or "").strip()
    submitted_password = submitted_password or ""
    rate_key = login_rate_limit_key(f'{user_model.__name__.lower()}:{submitted_id}')

    if login_is_rate_limited(rate_key):
        flash("Too many sign-in attempts. Please wait 15 minutes and try again.")
        return render_template(template_name, csrf_token=csrf_token_func), 429

    lookup_attrs = lookup_attrs or (user_id_attr,)

    filters = [
        func.lower(func.trim(getattr(user_model, attr))) == submitted_id.lower()
        for attr in lookup_attrs
    ]

    user = user_model.query.filter(or_(*filters)).first()

    if (
        user_model is Admin
        and not user
        and submitted_id
        and submitted_password
        and Admin.query.count() == 0
    ):
        user = Admin(
            admin_id=submitted_id,
            password=generate_password_hash(submitted_password),
        )
        db.session.add(user)
        db.session.flush()

    if (
        user_model is Student
        and not user
        and submitted_id
        and submitted_password
        and "@" not in submitted_id
        and AllowedStudent.query.filter(
            func.lower(func.trim(AllowedStudent.student_id)) == submitted_id.lower()
        ).first()
    ):
        user = Student(
            student_id=submitted_id,
            name=f"Student {submitted_id}",
            department=DEPARTMENTS[0],
            graduation_year=datetime.now().year,
            email=f"{submitted_id}@audaily.local",
            password=generate_password_hash(submitted_password),
            is_verified=True,
        )
        db.session.add(user)
        db.session.flush()

    password_ok = bool(user and submitted_password and verify_password_and_upgrade(user, submitted_password))
    print("ACTUAL LOGIN:", bool(user), password_ok)
    env_password_ok = bool(submitted_password and env_login_password_matches(user_model, submitted_id, submitted_password))
    if env_password_ok and (user or user_model is Admin):
        repaired_user = ensure_env_login_account(user_model, submitted_id, submitted_password)
        if repaired_user:
            user = repaired_user
        password_ok = True

    if not password_ok:
        current_app.logger.warning(
            "%s login rejected: found=%s password_submitted=%s id_length=%s",
            user_model.__name__,
            bool(user),
            bool(submitted_password),
            len(submitted_id),
        )

    if password_ok:
        clear_login_rate_limit(rate_key)
        db.session.commit()
        session.clear()
        session[user_model.__name__.lower()] = getattr(user, user_id_attr) if user else submitted_id
        return redirect(url_for(success_redirect_endpoint, _external=True))
    else:
        db.session.rollback()
        record_failed_login(rate_key)
        flash(failure_message)
        return render_template(template_name, csrf_token=csrf_token_func)
DEPARTMENTS = sorted([
    'Civil Engineering',
    'Mechanical Engineering',
    'Electrical Engineering',
    'Electronics & Communication Engineering',
    'Computer Science & Systems Engineering',
    'Information Technology & Computer Applications',
    'Chemical Engineering',
    'Metallurgical Engineering',
    'Instrument Technology',
    'Marine Engineering'
])

# LOST & FOUND CATEGORIES
LOST_FOUND_CATEGORIES = [
    'Electronics', 'Books', 'Clothing', 'Keys', 'Wallet/Purse', 'ID Card',
    'Bags', 'Jewelry', 'Stationery', 'Other'
]

# PROJECT TECHNOLOGIES (for filtering)
PROJECT_TECHNOLOGIES = sorted([
    'Python', 'Java', 'JavaScript', 'C++', 'C', 'HTML', 'CSS', 'React', 'Angular', 'Vue.js',
    'Flask', 'Django', 'Node.js', 'Express.js', 'Spring Boot', 'SQL', 'MySQL', 'PostgreSQL',
    'MongoDB', 'AWS', 'Azure', 'GCP', 'Docker', 'Kubernetes', 'Machine Learning', 'AI',
    'Data Science', 'Android', 'iOS', 'Web Development', 'Mobile Development', 'UI/UX',
    'Cloud Computing', 'Cybersecurity', 'Blockchain', 'IoT', 'Embedded Systems', 'Robotics',
    'CAD', 'SolidWorks', 'AutoCAD', 'MATLAB', 'Simulink', 'Arduino', 'Raspberry Pi'
])

# SUGGESTION CATEGORIES
SUGGESTION_CATEGORIES = ['Campus Facilities', 'Academic Policy', 'Student Life', 'Events', 'Technology', 'Other']

# JOB CATEGORIES
JOB_CATEGORIES = [
    '💼 Full-time jobs',
    '🧑‍💻 Internships',
    '🧪 Research opportunities',
    '🎓 Scholarships',
    '🏆 Hackathons',
    '📢 Campus ambassador roles',
    '💰 Freelance / Part-time gigs'
]

# =========================
# DATABASE MODELS
# =========================

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(100))
    department = db.Column(db.String(100))
    graduation_year = db.Column(db.Integer)
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20))
    password = db.Column(db.String(200))
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    profile_pic = db.Column(db.String(200))
    skills = db.relationship('StudentSkill', backref='student', lazy=True, cascade="all, delete-orphan")

class AllowedStudent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    description = db.Column(db.Text)
    date = db.Column(db.String(50))
    department = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)
    posted_by = db.Column(db.String(100))
    # Add user_id for robust linking, nullable for old/admin posts
    user_id = db.Column(db.String(20), nullable=True)
    image_file = db.Column(db.String(200))

    likes = db.relationship('EventLike', backref='event', lazy=True, cascade="all, delete-orphan")
    comments = db.relationship('Comment', backref='event', lazy=True, cascade="all, delete-orphan")
    registrations = db.relationship('EventRegistration', backref='event', lazy=True, cascade="all, delete-orphan")

    @property
    def is_video(self):
        if self.image_file:
            ext = self.image_file.rsplit('.', 1)[1].lower()
            return ext in {'mp4', 'mov', 'avi', 'webm'}
        return False

class EventLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20))
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.String(20), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.now())

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50)) # 'new_event', 'reminder', 'alert'
    event_id = db.Column(db.Integer, nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

    __table_args__ = (
        db.Index('ix_notification_user_unread', 'user_id', 'is_read'),
    )

class EventRegistration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)

class NewsPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.String(20), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    profile_pic = db.Column(db.String(200))
    image_file = db.Column(db.String(200), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

    likes = db.relationship('NewsLike', backref='news_post', lazy=True, cascade="all, delete-orphan")
    comments = db.relationship('NewsComment', backref='news_post', lazy=True, cascade="all, delete-orphan")

    @property
    def is_video(self):
        if self.image_file:
            ext = self.image_file.rsplit('.', 1)[1].lower()
            return ext in {'mp4', 'mov', 'avi', 'webm'}
        return False

class NewsLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20))
    post_id = db.Column(db.Integer, db.ForeignKey('news_post.id'))

class NewsComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.String(20), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('news_post.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.now())

class LostItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10), nullable=False) # 'Lost' or 'Found'
    item_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    location = db.Column(db.String(100))
    category = db.Column(db.String(50), nullable=True) # Added for filtering
    image_file = db.Column(db.String(200))
    contact = db.Column(db.String(50))
    user_id = db.Column(db.String(20), nullable=False)
    is_resolved = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(100))
    department = db.Column(db.String(100))
    year = db.Column(db.String(20)) # e.g. "1st Year"
    file_path = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.String(20), nullable=False)
    user_name = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

    comments = db.relationship('ResourceComment', backref='resource', cascade="all, delete-orphan")
    saves = db.relationship('SavedResource', backref='resource_saved', cascade="all, delete-orphan")

    @property
    def is_pdf(self):
        return self.file_path.lower().endswith('.pdf')

class ResourceComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.String(20), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.now())

class SavedResource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)

class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)
    options = db.relationship('PollOption', backref='poll', lazy=True, cascade="all, delete-orphan")

class PollOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(100), nullable=False)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)

class PollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), nullable=False)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('poll_option.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'poll_id', name='_user_poll_uc'),)

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    admin_response = db.Column(db.Text, nullable=True)
    responded_at = db.Column(db.DateTime, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

class AdminNotification(db.Model):
    """An actionable alert shown to administrators in the admin console."""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(30), nullable=False)  # feedback or report
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), nullable=True) # Nullable for anonymous
    report_type = db.Column(db.String(50), nullable=False) # Spam, Fake Job, Bug, Abuse, Other
    description = db.Column(db.Text, nullable=False)
    image_file = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default='Pending') # Pending, In Progress, Resolved
    priority = db.Column(db.String(20), default='Low') # High, Medium, Low
    admin_response = db.Column(db.Text, nullable=True)
    responded_at = db.Column(db.DateTime, nullable=True)

    # Target context (What is being reported?)
    item_type = db.Column(db.String(50), nullable=True) # e.g., 'Event', 'NewsPost', 'User'
    item_id = db.Column(db.Integer, nullable=True) # ID of the offending post
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)


class PhoneRecoveryAttempt(db.Model):
    """Server-side limits for phone-based password recovery attempts."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    window_started_at = db.Column(db.DateTime, nullable=True)
    send_count = db.Column(db.Integer, default=0, nullable=False)
    failed_verifications = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)


class AuthRateLimit(db.Model):
    """Shared, database-backed limits that remain effective across workers/restarts."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False, index=True)
    window_started_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)

class DepartmentInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(100), nullable=False, unique=True)
    keywords = db.Column(db.Text, nullable=False) # Store as comma-separated string

    def get_keywords_list(self):
        return [kw.strip() for kw in self.keywords.split(',')] if self.keywords else []


class RecoveryRequest(db.Model):
    """A password-recovery request that requires an administrator identity check."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), nullable=False, index=True)
    recovery_email = db.Column(db.String(120), nullable=True)
    contact_note = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), nullable=False, default='Pending', index=True)
    reviewed_by = db.Column(db.String(20), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

class EmailVerificationToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), nullable=False, index=True)
    token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

class Follower(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # The user doing the following
    follower_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=False)
    # The user being followed
    followed_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)
    __table_args__ = (db.UniqueConstraint('follower_id', 'followed_id', name='_follower_followed_uc'),)

class PrivateMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=False)
    receiver_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=False)
    content = db.Column(db.Text, nullable=True)
    image_file = db.Column(db.String(200), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)
    is_read = db.Column(db.Boolean, default=False)

    __table_args__ = (
        db.Index('ix_private_message_receiver_unread', 'receiver_id', 'is_read'),
        db.Index('ix_private_message_sender_timestamp', 'sender_id', 'timestamp'),
        db.Index('ix_private_message_receiver_timestamp', 'receiver_id', 'timestamp'),
    )

class AnonymousDoubt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.String(20), nullable=False)
    file_path = db.Column(db.String(200), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)
    replies = db.relationship('DoubtReply', backref='doubt', lazy=True, cascade="all, delete-orphan")

    @property
    def is_image(self):
        if self.file_path:
            ext = self.file_path.rsplit('.', 1)[1].lower()
            return ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        return False

class DoubtReply(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.String(20), nullable=False)
    doubt_id = db.Column(db.Integer, db.ForeignKey('anonymous_doubt.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task = db.Column(db.String(255), nullable=False)
    due_date = db.Column(db.String(50), nullable=True)
    is_completed = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

class JobPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255))
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    link = db.Column(db.String(500))
    image_file = db.Column(db.String(200), nullable=True) # Added for job post images
    user_id = db.Column(db.String(20), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

class StudentSkill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=False)
    skill_name = db.Column(db.String(100), nullable=False)
    endorsements = db.relationship('SkillEndorsement', backref='skill', lazy=True, cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint('student_id', 'skill_name', name='_student_skill_uc'),)

class SkillEndorsement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('student_skill.id'), nullable=False)
    # The student who is giving the endorsement
    endorser_student_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('skill_id', 'endorser_student_id', name='_skill_endorser_uc'),)

class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text)
    department = db.Column(db.String(100), nullable=False) # e.g., 'General', 'Exam Section', 'CSE'
    file_path = db.Column(db.String(200), nullable=True)
    posted_by_admin_id = db.Column(db.String(20), db.ForeignKey('admin.admin_id'), nullable=False)
    is_urgent = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

    admin = db.relationship('Admin', backref='notices')

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    technologies = db.Column(db.String(500)) # Comma-separated string of technologies
    image_file = db.Column(db.String(200), nullable=True)
    video_file = db.Column(db.String(200), nullable=True)
    github_link = db.Column(db.String(500), nullable=True)
    live_demo_link = db.Column(db.String(500), nullable=True)
    user_id = db.Column(db.String(20), db.ForeignKey('student.student_id'), nullable=True)
    user_name = db.Column(db.String(100), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)

    likes = db.relationship('ProjectLike', backref='project', lazy=True, cascade="all, delete-orphan")
    comments = db.relationship('ProjectComment', backref='project', lazy=True, cascade="all, delete-orphan")

    @property
    def is_video(self):
        if self.video_file:
            ext = self.video_file.rsplit('.', 1)[1].lower()
            return ext in VIDEO_EXTENSIONS
        return False

class ProjectLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'project_id', name='_user_project_like_uc'),)

class ProjectComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.String(20), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)

class Suggestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.String(20), nullable=True) # Nullable for anonymous submissions
    admin_notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='New', nullable=False) # New, Under Review, Implemented, Rejected
    timestamp = db.Column(db.DateTime, default=datetime.now, nullable=False)


# =========================
# NOTIFICATION LOGIC
# =========================


def create_admin_notification(category, message, endpoint):
    """Queue an administrator alert within the same database transaction as its event."""
    db.session.add(AdminNotification(
        category=category,
        message=message,
        link=url_for(endpoint),
    ))


def send_admin_alert(subject, title, details):
    """Email the admin without letting an email outage lose the in-app alert."""
    if not current_app.config.get('ADMIN_ALERT_RECIPIENT'):
        current_app.logger.warning('Admin alert email is not configured; keeping the in-app alert only.')
        return
    try:
        mail.send(Message(
            subject=subject,
            recipients=[current_app.config['ADMIN_ALERT_RECIPIENT']],
            html=render_template('admin_alert_email.html', title=title, details=details),
        ))
    except Exception:
        current_app.logger.exception('Unable to send admin alert email')


def notify_student_of_admin_reply(student_id, reply, subject, context):
    """Deliver an admin reply in the app and, when possible, to the student's email."""
    student = Student.query.filter_by(student_id=student_id).first()
    if not student:
        return
    db.session.add(Notification(
        user_id=student_id,
        message=f'Admin replied to your {context}: {reply[:190]}',
        type='admin_reply',
    ))
    db.session.commit()
    if student.email:
        try:
            mail.send(Message(
                subject=subject,
                recipients=[student.email],
                html=render_template('student_admin_reply_email.html', name=student.name, context=context, reply=reply),
            ))
        except Exception:
            current_app.logger.exception('Unable to send student admin-reply email')


def normalize_indian_mobile(value):
    """Return a 10-digit Indian mobile number, or None for invalid input."""
    digits = re.sub(r'\D', '', value or '')
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    return digits if len(digits) == 10 and digits[0] in '6789' else None


def fast2sms_otp_request(endpoint, payload):
    """Call Fast2SMS Smart OTP without exposing provider errors to users."""
    if not current_app.config.get('FAST2SMS_API_KEY') or not current_app.config.get('FAST2SMS_OTP_ID'):
        raise RuntimeError('Phone recovery is not configured. Set FAST2SMS_API_KEY and FAST2SMS_OTP_ID.')
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(
        f'https://www.fast2sms.com/dev/otp/{endpoint}', data=data, method='POST',
        headers={'Authorization': current_app.config['FAST2SMS_API_KEY'], 'Content-Type': 'application/json'},
    )
    try:
        with urlrequest.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        current_app.logger.warning('Fast2SMS %s request failed: %s', endpoint, error)
        return {'return': False}

def check_upcoming_events(user_id):
    """Checks for events happening tomorrow and creates reminders."""
    today = datetime.now().date()
    today_key = today.strftime('%Y-%m-%d')
    if session.get('event_reminders_checked_on') == today_key:
        return

    tomorrow_str = (today + timedelta(days=1)).strftime('%Y-%m-%d')

    # Directly query events matching tomorrow's date string
    upcoming_events = Event.query.filter_by(date=tomorrow_str).all()
    if not upcoming_events:
        session['event_reminders_checked_on'] = today_key
        return

    event_ids = [event.id for event in upcoming_events]
    existing_event_ids = {
        row[0] for row in db.session.query(Notification.event_id).filter(
            Notification.user_id == user_id,
            Notification.type == 'reminder',
            Notification.event_id.in_(event_ids)
        ).all()
    }

    for event in upcoming_events:
        if event.id not in existing_event_ids:
            msg = f"Reminder: '{event.title}' is happening tomorrow!"
            db.session.add(Notification(user_id=user_id, message=msg, type='reminder', event_id=event.id))
    db.session.commit()
    session['event_reminders_checked_on'] = today_key

# =========================
# HOME PAGE
# =========================

bp = Blueprint('main', __name__)
api_bp = Blueprint('api', __name__, url_prefix='/api/v1')


@bp.route('/')
def home():
    user_id = session.get('student') or session.get('admin')
    if not user_id:
        # If not logged in, show the welcome landing page
        return render_template("welcome.html") # This remains the same

    # CRITICAL FIX: If admin clicks "Home", redirect to their dashboard, not the student feed.
    if 'admin' in session:
        return redirect(url_for('main.admin_dashboard'))

    student = None
    current_user_name = None
    if 'student' in session:
        student = getattr(g, "current_student", None)
        if not student:
            session.clear()
            return redirect(url_for('main.home'))
        current_user_name = student.name
        check_upcoming_events(session['student'])

    # 2. Upcoming Event Reminders (next 7 days)
    today_str = datetime.now().strftime('%Y-%m-%d')
    next_week = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
    upcoming_events = Event.query.filter(Event.date >= today_str, Event.date <= next_week).order_by(Event.date.asc()).limit(4).all()

    # 3. Recommended Events (Top 4)
    all_events = Event.query.order_by(Event.id.desc()).limit(20).all() # Fetch a pool of recent events
    recommended_events = []
    if student:
        dept_interests_obj = DepartmentInterest.query.filter_by(department=student.department).first()
        student_interests_keywords = dept_interests_obj.get_keywords_list() if dept_interests_obj else []

        def get_recommendation_score(event):
            score = 0
            if event.department == student.department:
                score += 10
            elif event.department == 'General':
                score += 5
            content = (event.title + " " + event.description).lower()
            for kw in student_interests_keywords:
                if kw in content:
                    score += 2
            return score

        for event in all_events:
            event.recommendation_score = get_recommendation_score(event)
        
        all_events.sort(key=lambda x: x.recommendation_score, reverse=True)
        recommended_events = all_events[:4]

    # 4. Recent Unread Notifications
    unread_notifications = Notification.query.filter_by(user_id=student.student_id, is_read=False).order_by(Notification.timestamp.desc()).limit(4).all()

    return render_template(
        "dashboard.html",
        current_user_name=current_user_name,
        upcoming_events=upcoming_events,
        recommended_events=recommended_events,
        unread_notifications=unread_notifications
    )

@bp.route('/events/<int:event_id>')
def event_detail(event_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    event = Event.query.get_or_404(event_id)
    user_id = session.get('student') or session.get('admin')
    user_liked = EventLike.query.filter_by(user_id=user_id, event_id=event.id).first() is not None
    is_registered = False
    if 'student' in session:
        is_registered = EventRegistration.query.filter_by(user_id=session['student'], event_id=event.id).first() is not None

    return render_template(
        "event_detail.html",
        event=event,
        user_liked=user_liked,
        is_registered=is_registered,
        like_count=EventLike.query.filter_by(event_id=event.id).count(),
        registration_count=EventRegistration.query.filter_by(event_id=event.id).count()
    )

# =========================
# RESUME ANALYZER
# =========================

RESUME_SKILL_KEYWORDS = {
    "Programming": ["python", "java", "javascript", "c", "c++", "sql", "html", "css", "php"],
    "Frameworks": ["flask", "django", "react", "node", "express", "spring", "bootstrap", "tailwind"],
    "Databases": ["mysql", "postgresql", "mongodb", "sqlite", "oracle", "firebase"],
    "Tools": ["git", "github", "docker", "linux", "aws", "postman", "figma", "excel"],
    "Core CS": ["data structures", "algorithms", "oops", "dbms", "operating system", "computer networks"],
    "Soft Skills": ["leadership", "communication", "teamwork", "problem solving", "presentation"]
}

RESUME_ACTION_VERBS = [
    "built", "developed", "designed", "implemented", "created", "optimized", "improved",
    "automated", "integrated", "deployed", "managed", "led", "analyzed", "tested"
]

RESUME_SECTIONS = {
    "Education": ["education", "academic"],
    "Skills": ["skills", "technical skills", "technologies"],
    "Projects": ["projects", "academic projects", "major project"],
    "Experience": ["experience", "internship", "work experience"],
    "Certifications": ["certifications", "certificates", "achievements"]
}

COURSE_SUGGESTIONS = {
    "python": {"name": "Python for Everybody", "platform": "Coursera", "url": "https://www.coursera.org/specializations/python"},
    "sql": {"name": "SQL for Data Science", "platform": "Coursera", "url": "https://www.coursera.org/learn/sql-for-data-science"},
    "git": {"name": "Introduction to Git and GitHub", "platform": "Coursera", "url": "https://www.coursera.org/learn/introduction-git-github"},
    "github": {"name": "Introduction to Git and GitHub", "platform": "Coursera", "url": "https://www.coursera.org/learn/introduction-git-github"},
    "data structures": {"name": "Data Structures & Algorithms", "platform": "Coursera", "url": "https://www.coursera.org/specializations/data-structures-algorithms"},
    "algorithms": {"name": "Data Structures & Algorithms", "platform": "Coursera", "url": "https://www.coursera.org/specializations/data-structures-algorithms"},
    "html": {"name": "HTML, CSS, and Javascript", "platform": "Coursera", "url": "https://www.coursera.org/learn/html-css-javascript-for-web-developers"},
    "css": {"name": "HTML, CSS, and Javascript", "platform": "Coursera", "url": "https://www.coursera.org/learn/html-css-javascript-for-web-developers"},
    "javascript": {"name": "HTML, CSS, and Javascript", "platform": "Coursera", "url": "https://www.coursera.org/learn/html-css-javascript-for-web-developers"},
    "flask": {"name": "REST APIs with Flask and Python", "platform": "Udemy", "url": "https://www.udemy.com/course/rest-api-flask-and-python/"},
    "docker": {"name": "Docker for the Absolute Beginner", "platform": "Udemy", "url": "https://www.udemy.com/course/docker-for-the-absolute-beginner/"},
    "aws": {"name": "AWS Certified Cloud Practitioner", "platform": "Udemy", "url": "https://www.udemy.com/course/aws-certified-cloud-practitioner-new/"},
    "react": {"name": "React - The Complete Guide", "platform": "Udemy", "url": "https://www.udemy.com/course/react-the-complete-guide-incl-redux/"}
}

def extract_resume_text(file_storage):
    filename = secure_filename(file_storage.filename or "")
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ""
    data = file_storage.read()

    if ext == "txt":
        return data.decode("utf-8", errors="ignore")

    if ext == "pdf":
        try:
            # strict=False accepts many PDFs produced by online resume builders
            # that do not follow every PDF structural rule exactly.
            reader = PdfReader(io.BytesIO(data), strict=False)
        except Exception as exc:
            raise ValueError("This PDF could not be opened. Please export the resume again as a standard PDF and try once more.") from exc
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if unlocked == 0:
                raise ValueError("This PDF is password-protected. Please upload an unlocked copy of your resume.")
        try:
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            raise ValueError(
                "This PDF opened successfully, but its text could not be read. "
                "Please export it again as a text-based PDF or upload the DOCX version."
            ) from exc
        extracted_text = "\n".join(pages).strip()
        if not extracted_text:
            raise ValueError("This PDF appears to be a scanned image with no selectable text. Please upload a text-based PDF, DOCX, or TXT file.")
        return extracted_text

    if ext == "docx":
        with zipfile.ZipFile(io.BytesIO(data)) as docx_file:
            xml_content = docx_file.read("word/document.xml")
        root = ET.fromstring(xml_content)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for para in root.findall(".//w:p", namespace):
            text = "".join(node.text or "" for node in para.findall(".//w:t", namespace))
            if text.strip():
                paragraphs.append(text)
        return "\n".join(paragraphs)

    raise ValueError("Unsupported file type. Please upload PDF, DOCX, or TXT.")

def keyword_hits(text, keywords):
    lowered = text.lower()
    return sorted({keyword for keyword in keywords if keyword in lowered})

def analyze_resume_text(text, job_description=""):
    normalized = re.sub(r"\s+", " ", text).strip()
    lowered = normalized.lower()
    words = re.findall(r"\b[a-zA-Z][a-zA-Z+#.]*\b", lowered)
    word_count = len(words)

    checks = []
    strengths = []
    improvements = []
    score = 0

    def add_check(label, passed, points, tip):
        nonlocal score
        if passed:
            score += points
            checks.append({"label": label, "status": "Good", "points": points})
            strengths.append(label)
        else:
            checks.append({"label": label, "status": "Needs work", "points": 0})
            improvements.append(tip)

    email_found = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", normalized))
    phone_found = bool(re.search(r"(\+91[\s-]?)?[6-9]\d{9}\b", normalized))
    links_found = bool(re.search(r"(linkedin\.com|github\.com|portfolio|hackerrank|leetcode)", lowered))
    add_check("Contact details", email_found and phone_found, 10, "Add a professional email and Indian mobile number at the top.")
    add_check("Profile links", links_found, 8, "Add LinkedIn, GitHub, portfolio, or coding-profile links.")

    found_sections = {
        section: any(label in lowered for label in labels)
        for section, labels in RESUME_SECTIONS.items()
    }
    add_check("Core resume sections", sum(found_sections.values()) >= 4, 14, "Include clear sections for Education, Skills, Projects, Experience/Internship, and Certifications.")
    # Add a bonus for having all sections, as it shows a very complete resume.
    if sum(found_sections.values()) == 5:
        score += 5
        strengths.append("Comprehensive structure")

    skills_by_group = {
        group: keyword_hits(lowered, keywords)
        for group, keywords in RESUME_SKILL_KEYWORDS.items()
    }
    matched_skills = sorted({skill for skills in skills_by_group.values() for skill in skills})
    total_skills = sum(len(items) for items in skills_by_group.values())
    # Tiered scoring for skills to better reward comprehensive resumes.
    if total_skills >= 15:
        add_check("Technical keyword coverage", True, 18, "")
    elif total_skills >= 8:
        add_check("Technical keyword coverage", True, 12, "")
    else:
        add_check("Technical keyword coverage", False, 0, "Add more role-relevant technical skills such as languages, frameworks, databases, tools, and CS fundamentals.")

    project_terms = keyword_hits(lowered, ["project", "mini project", "major project", "application", "system", "dashboard", "portal"])
    add_check("Project visibility", len(project_terms) >= 2 and found_sections.get("Projects"), 12, "Make projects easy to find and mention tech stack, your role, and outcome.")

    quantified = len(re.findall(r"(\d+%|\d+\+|\b\d{2,}\b)", normalized))
    add_check("Measurable impact", quantified >= 2, 10, "Add numbers where possible: users, accuracy, performance, marks, team size, or time saved.")

    action_hits = keyword_hits(lowered, RESUME_ACTION_VERBS)
    add_check("Action-oriented writing", len(action_hits) >= 5, 10, "Start bullets with action verbs like Built, Developed, Implemented, Optimized, or Deployed.")

    soft_skills = keyword_hits(lowered, [
        "communication", "teamwork", "leadership", "problem solving", "problem-solving",
        "adaptability", "time management", "collaboration", "critical thinking", "creativity"
    ])

    ats_symbol_codes = {0x25A1, 0x25A0, 0x25CF, 0x25C6, 0x2605, 0x2713, 0x2714}
    ats_symbols = any(ord(char) in ats_symbol_codes for char in normalized)
    add_check("ATS-friendly formatting", not ats_symbols and word_count >= 180, 10, "Use simple headings, normal bullets, readable text, and avoid icon-heavy formatting.")

    ideal_length = 250 <= word_count <= 850
    add_check("Resume length", ideal_length, 6, "Keep a fresher resume around one page with roughly 250-850 meaningful words.")

    experience_match = re.search(r"\b(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", lowered)
    experience_years = experience_match.group(1) if experience_match else "—"
    education_match = re.search(r"\b(b\.?tech|b\.?e|bsc|b\.?sc|m\.?tech|m\.?e|msc|m\.?sc|mba|diploma)\b", lowered)
    education = education_match.group(1).replace('.', '').upper() if education_match else "—"
    project_count = len(re.findall(r"\b(?:mini|major|academic)?\s*projects?\b", lowered))

    passed_checks = sum(check["status"] == "Good" for check in checks)
    if ats_symbols or word_count < 100 or sum(found_sections.values()) < 2:
        ats_compatibility = "Not ATS Friendly"
    elif passed_checks >= 6:
        ats_compatibility = "ATS Friendly"
    else:
        ats_compatibility = "Needs Improvement"

    jd_match = None
    if job_description.strip():
        stop_words = {
            "and", "the", "for", "with", "you", "are", "this", "that", "will", "from", "our", "your",
            "have", "has", "can", "able", "work", "role", "team", "job", "candidate", "required",
            "preferred", "experience", "skills", "knowledge", "good", "strong"
        }
        jd_words = {
            word for word in re.findall(r"\b[a-zA-Z][a-zA-Z+#.]{2,}\b", job_description.lower())
            if word not in stop_words
        }
        resume_words = set(words)
        matched = sorted(jd_words & resume_words)
        missing = sorted(jd_words - resume_words)[:12]
        match_score = round((len(matched) / max(len(jd_words), 1)) * 100)
        jd_match = {"score": match_score, "matched": matched[:16], "missing": missing, "ai_analysis": "Local"}
        if match_score >= 35:
            score += 10
            strengths.append("Job description alignment")
        else:
            improvements.append("Customize the resume using important keywords from the target job description.")

    baseline_skills = ["python", "sql", "git", "github", "data structures", "algorithms", "html", "css", "javascript", "flask"]
    missing_skills = jd_match["missing"] if jd_match else [skill for skill in baseline_skills if skill not in matched_skills]
    learning_guides = {
        "python": "Python: complete a beginner course, then build two small automation or web projects.",
        "sql": "SQL: practise SELECT, JOIN, GROUP BY, and database design on sample datasets.",
        "git": "Git/GitHub: learn commits, branches, pull requests, then publish every project.",
        "github": "GitHub: create clean repositories with a README, screenshots, and setup steps.",
        "data structures": "Data Structures: study arrays, stacks, queues, linked lists, and trees; solve practice problems weekly.",
        "algorithms": "Algorithms: learn searching, sorting, recursion, and complexity; practise with timed problems.",
        "html": "HTML/CSS: build responsive pages and recreate two real-world layouts.",
        "css": "HTML/CSS: build responsive pages and recreate two real-world layouts.",
        "javascript": "JavaScript: practise DOM, async requests, and build an interactive mini-project.",
        "flask": "Flask: build a CRUD project with authentication, a database, and deployment notes."
    }
    learning_plan = [learning_guides.get(skill, f"Learn {skill.title()}: study its fundamentals and add one honest project example to your resume.") for skill in missing_skills[:6]]

    # New logic for course suggestions
    skill_actions = [
        {"skill": skill,
         "guide": learning_guides.get(skill, f"Learn {skill.title()} through its basics, then complete one small project and add it honestly to your resume."),
         "course": COURSE_SUGGESTIONS.get(skill)}
        for skill in missing_skills[:6]
    ]

    score = min(score, 100)
    if score >= 80:
        verdict = "Strong resume"
    elif score >= 60:
        verdict = "Good foundation"
    else:
        verdict = "Needs improvement"

    if not normalized:
        score = 0
        verdict = "Could not read resume text"
        improvements = ["Upload a text-readable PDF, DOCX, or TXT resume. Scanned image PDFs cannot be analyzed here."]

    return {
        "score": score,
        "verdict": verdict,
        "word_count": word_count,
        "checks": checks,
        "strengths": strengths[:6],
        "improvements": improvements[:8],
        "sections": found_sections,
        "skills_by_group": skills_by_group,
        "matched_skills": matched_skills,
        "technical_skills": matched_skills,
        "soft_skills": soft_skills,
        "missing_skills": missing_skills[:12],
        "weaknesses": [check["label"] for check in checks if check["status"] != "Good"],
        "ats_compatibility": ats_compatibility,
        "experience_years": experience_years,
        "education": education,
        "project_count": project_count,
        "learning_plan": learning_plan,
        "skill_actions": skill_actions,
        "action_verbs": action_hits,
        "jd_match": jd_match
    }

@bp.route('/resume_analyzer', methods=['GET', 'POST'])
@require_csrf
def resume_analyzer():
    if request.method == 'POST':
        if 'student' not in session and 'admin' not in session:
            flash('Please sign in before analyzing a resume.', 'warning') # This path is likely unreachable due to GET check
            return redirect(url_for('auth.student_login'))

        resume_file = request.files.get('resume')
        job_description = request.form.get('job_description', '')

        if not resume_file or resume_file.filename == '':
            flash('Please upload a resume file.', 'warning')
            return render_template('resume_analyzer.html'), 400

        ext = resume_file.filename.rsplit('.', 1)[1].lower() if '.' in resume_file.filename else ""
        if ext not in current_app.config['RESUME_EXTENSIONS']:
            flash(f"Please upload only {', '.join(sorted(app.config['RESUME_EXTENSIONS']))} files.", 'warning')
            return render_template('resume_analyzer.html'), 400

        try:
            text = extract_resume_text(resume_file)
            result = analyze_resume_text(text, job_description)
            return render_template('resume_analyzer.html', result=result, resume_filename=secure_filename(resume_file.filename))
        except ValueError as e:
            current_app.logger.info('Resume upload could not be read: %s', e)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': str(e)}), 422
            flash(str(e), 'warning')
            return render_template('resume_analyzer.html'), 422
        except Exception as e:
            # Use traceback to get detailed exception info for logging
            import traceback
            current_app.logger.error("--- RESUME ANALYSIS FAILED ---")
            current_app.logger.error(traceback.format_exc())
            error_message = "The resume could not be analyzed due to a server error. Please try again later."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                # CRITICAL FIX: Return a JSON error for AJAX, not an HTML page
                return jsonify({'error': error_message}), 500
            flash(error_message, 'danger')
            return render_template('resume_analyzer.html'), 500

    # Handle GET requests (just showing the page)
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))
    return render_template("resume_analyzer.html")

@bp.route('/placement', methods=['GET']) # Only GET for rendering the page
def placement():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))
    return redirect(url_for('main.resume_analyzer'))

@bp.route('/analyze_placement', methods=['POST']) # New route for AJAX POST
@require_csrf
def analyze_placement():
    if 'student' not in session and 'admin' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    resume_file = request.files.get('resume')
    job_description = request.form.get('job_link', '')

    if not resume_file or resume_file.filename == '':
        return jsonify({'success': False, 'error': 'Please upload a resume file.'})

    ext = resume_file.filename.rsplit('.', 1)[1].lower() if '.' in resume_file.filename else ""
    if ext not in current_app.config['RESUME_EXTENSIONS']:
        return jsonify({'success': False, 'error': f"Please upload only {', '.join(sorted(current_app.config['RESUME_EXTENSIONS']))} files."})

    try:
        text = extract_resume_text(resume_file)
        result = analyze_resume_text(text, job_description)
        return jsonify({'success': True, 'analysis': result})
    except Exception as e:
        import traceback
        current_app.logger.error("--- RESUME ANALYSIS (LEGACY AJAX) FAILED ---")
        current_app.logger.error(traceback.format_exc())
        # Return a specific error to the client for better debugging.
        return jsonify({'success': False, 'error': 'Resume analysis failed due to a server error. Please try again later.'}), 500


# =========================
# CAMPUS NEWS FEED
# =========================

@bp.route('/campus_news')
def campus_news():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    user_id = session.get('student') or session.get('admin')
    page = request.args.get('page', 1, type=int)
    feed_type = request.args.get('feed', 'all') # 'all', 'following', or 'department'
    per_page = 5 # Number of posts per page

    posts_query = NewsPost.query

    if feed_type == 'following' and 'student' in session:
        # Get the IDs of all users the current student is following to filter the feed
        followed_users = Follower.query.filter_by(follower_id=user_id).with_entities(Follower.followed_id).all()
        followed_ids = [f[0] for f in followed_users]
        if followed_ids:
            posts_query = posts_query.filter(NewsPost.user_id.in_(followed_ids))
        else:
            # If user follows no one, show an empty feed for 'following' tab
            posts_query = posts_query.filter(NewsPost.id == -1) # No posts will match this
    elif feed_type == 'department' and 'student' in session:
        student = Student.query.filter_by(student_id=user_id).first()
        if student and student.department:
            # Find all users in the same department
            dept_users = Student.query.filter_by(department=student.department).with_entities(Student.student_id).all()
            dept_ids = [u[0] for u in dept_users]
            if dept_ids:
                # Show posts from department peers or from admins
                posts_query = posts_query.filter(or_(NewsPost.user_id.in_(dept_ids), NewsPost.is_admin == True))
            else:
                posts_query = posts_query.filter(NewsPost.is_admin == True)
        else:
            posts_query = posts_query.filter(NewsPost.id == -1)

    posts_pagination = posts_query.order_by(NewsPost.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    posts = posts_pagination.items

    # Augment posts with like/comment data
    for post in posts:
        post.like_count = NewsLike.query.filter_by(post_id=post.id).count()
        post.user_liked = NewsLike.query.filter_by(user_id=user_id, post_id=post.id).first() is not None
        post.comments = NewsComment.query.filter_by(post_id=post.id).order_by(NewsComment.timestamp.asc()).all()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Render only the posts for AJAX requests
        return render_template('_news_posts.html', posts=posts, current_user_id=user_id)

    return render_template("campus_news.html", posts=posts, pagination=posts_pagination, feed_type=feed_type, has_next=posts_pagination.has_next)

@bp.route('/add_news_post', methods=['POST'])
@require_csrf
def add_news_post():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    content = request.form.get('content')
    if not content or len(content.strip()) == 0:
        flash("Post content cannot be empty.")
        return redirect(url_for('main.campus_news'))

    # Handle Image Upload
    image = request.files.get('image')
    image_filename = None
    if image and image.filename != '':
        if allowed_media_file(image.filename):
            image_filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
            image.save(os.path.join(current_app.config['UPLOAD_FOLDER'], image_filename))
        else:
            flash("Invalid file type. Only images and videos are allowed.")
            return redirect(url_for('main.campus_news')) # Ensure redirect on error

    user_id = session.get('student') or session.get('admin')
    user_name = "Admin"
    profile_pic = None
    is_admin = 'admin' in session

    if 'student' in session:
        student = Student.query.filter_by(student_id=user_id).first()
        if student:
            user_name = student.name
            profile_pic = student.profile_pic

    new_post = NewsPost(
        content=content,
        user_id=user_id,
        user_name=user_name,
        profile_pic=profile_pic,
        image_file=image_filename,
        is_admin=is_admin
    )
    db.session.add(new_post)
    db.session.commit()
    flash("Your post has been published!")
    return redirect(url_for('main.campus_news'))

@bp.route('/edit_news_post/<int:post_id>', methods=['POST'])
@require_csrf
def edit_news_post(post_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    post = NewsPost.query.get_or_404(post_id)
    current_user = session.get('student') or session.get('admin')

    if post.user_id == current_user or 'admin' in session:
        new_content = request.form.get('content')
        if new_content and new_content.strip():
            post.content = new_content.strip()
            db.session.commit()

    return redirect(safe_redirect_target(url_for('main.campus_news')))

@bp.route('/delete_news_post/<int:post_id>', methods=['POST'])
@require_csrf
def delete_news_post(post_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    post = NewsPost.query.get_or_404(post_id)
    current_user = session.get('student') or session.get('admin')

    if post.user_id == current_user or 'admin' in session:
        remove_uploaded_media(post.image_file)
        db.session.delete(post)
        db.session.commit()
        flash("Post deleted.")
    else:
        flash("You are not authorized to delete this post.")

    return redirect(url_for('main.campus_news'))

@bp.route('/like_news/<int:post_id>', methods=['POST'])
@require_csrf
def like_news_post(post_id):
    if 'student' not in session and 'admin' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    user_id = session.get('student') or session.get('admin')

    existing_like = NewsLike.query.filter_by(user_id=user_id, post_id=post_id).first()

    if existing_like:
        db.session.delete(existing_like)
    else:
        new_like = NewsLike(user_id=user_id, post_id=post_id)
        db.session.add(new_like)

    db.session.commit()
    return jsonify({'success': True, 'likes': NewsLike.query.filter_by(post_id=post_id).count(), 'liked': not existing_like})

@bp.route('/comment_news/<int:post_id>', methods=['POST'])
@require_csrf
def add_news_comment(post_id):
    if 'student' not in session and 'admin' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    content = request.form.get('content')
    if content and content.strip():
        user_id = session.get('student') or session.get('admin')
        user_name = "Admin"
        student = None

        if 'student' in session:
            student = Student.query.filter_by(student_id=user_id).first()
            if student:
                user_name = student.name

        comment = NewsComment(content=content, user_id=user_id, user_name=user_name, post_id=post_id)
        db.session.add(comment)
        db.session.commit()

        return jsonify({
            'success': True,
            'user_name': user_name,
            'content': content,
            'timestamp': "Just now",
            'comment_id': comment.id,
            'user_profile_pic': student.profile_pic if student else None,
            'user_id': user_id
        })

    return jsonify({'success': False})

@bp.route('/delete_news_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def delete_news_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    comment = NewsComment.query.get_or_404(comment_id)
    current_user = session.get('student') or session.get('admin')

    if comment.user_id == current_user or 'admin' in session:
        db.session.delete(comment)
        db.session.commit()

    return redirect(url_for('main.campus_news'))

@bp.route('/edit_news_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def edit_news_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    comment = NewsComment.query.get_or_404(comment_id)
    current_user = session.get('student') or session.get('admin')

    if comment.user_id == current_user or 'admin' in session:
        new_content = request.form.get('content')
        if new_content and new_content.strip():
            comment.content = new_content.strip()
            db.session.commit()

    return redirect(safe_redirect_target(url_for('main.campus_news')))

@bp.route('/notifications')
def notifications():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    user_id = session['student']
    notifs = Notification.query.filter_by(user_id=user_id).order_by(
        Notification.timestamp.desc()
    ).limit(100).all()

    return render_template("notifications.html", notifications=notifs)

@bp.route('/notifications/mark_read/<int:id>', methods=['GET', 'POST'])
@require_csrf
def mark_notification_read(id):
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    if request.method == 'GET':
        flash("Use the notification item to mark it as read.")
        return redirect(url_for('main.notifications'))

    notif = Notification.query.get_or_404(id)
    if notif.user_id == session['student']:
        notif.is_read = True
        db.session.commit()
        clear_nav_count_cache()
    return redirect(url_for('main.notifications'))

@bp.route('/notifications/mark_all_read', methods=['GET', 'POST'])
@require_csrf
def mark_all_notifications_read():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    if request.method == 'GET':
        flash("Use the mark-all action on the notifications page.")
        return redirect(url_for('main.notifications'))

    user_id = session['student']
    Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()
    clear_nav_count_cache()
    return redirect(url_for('main.notifications'))

@bp.route('/like/<int:event_id>', methods=['GET', 'POST'])
@require_csrf
def like_event(event_id):
    if request.method == 'GET':
        flash("Use the heart button on an event to like it.")
        return redirect(url_for('main.home'))

    if 'student' not in session and 'admin' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    user_id = session.get('student') or session.get('admin')

    existing_like = EventLike.query.filter_by(user_id=user_id, event_id=event_id).first()

    if existing_like:
        db.session.delete(existing_like)
    else:
        new_like = EventLike(user_id=user_id, event_id=event_id)
        db.session.add(new_like)

    db.session.commit()
    payload = {
        'success': True,
        'likes': EventLike.query.filter_by(event_id=event_id).count(),
        'liked': not existing_like,
    }
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify(payload)
    return redirect(safe_redirect_target(url_for('main.home')))

@bp.route('/register_event/<int:event_id>', methods=['GET', 'POST'])
@require_csrf
def register_event(event_id):
    if request.method == 'GET':
        flash("Use the Register button on an event to update your registration.")
        return redirect(url_for('main.home'))

    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    user_id = session['student']
    existing_reg = EventRegistration.query.filter_by(user_id=user_id, event_id=event_id).first()

    if existing_reg:
        db.session.delete(existing_reg)
        flash("You have unregistered from this event.")
    else:
        new_reg = EventRegistration(user_id=user_id, event_id=event_id)
        db.session.add(new_reg)
        flash("Successfully registered for the event!")

    db.session.commit()
    return redirect(safe_redirect_target(url_for('main.home')))

@bp.route('/comment/<int:event_id>', methods=['GET', 'POST'])
@require_csrf
def add_comment(event_id):
    if request.method == 'GET':
        flash("Use the comment box on an event to add a comment.")
        return redirect(url_for('main.home'))

    if 'student' not in session and 'admin' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    content = request.form.get('content')
    if content and content.strip():
        user_id = session.get('student') or session.get('admin')
        user_name = "Admin"
        student = None # Initialize to prevent UnboundLocalError for admin

        if 'student' in session:
            student = Student.query.filter_by(student_id=user_id).first()
            if student:
                user_name = student.name

        comment = Comment(content=content, user_id=user_id, user_name=user_name, event_id=event_id)
        db.session.add(comment)
        db.session.commit()

        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({
                'success': True,
                'user_name': user_name,
                'content': content,
                'timestamp': "Just now",
                'comment_id': comment.id,
                'user_profile_pic': student.profile_pic if student else None,
                'user_id': user_id
            })
        flash("Comment added.")
        return redirect(safe_redirect_target(url_for('main.home')))

    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({'success': False})
    flash("Comment cannot be empty.")
    return redirect(safe_redirect_target(url_for('main.home')))

@bp.route('/delete_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def delete_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    comment = Comment.query.get_or_404(comment_id)
    current_user = session.get('student') or session.get('admin')

    # Allow deletion if user owns the comment OR is an admin
    if comment.user_id == current_user or 'admin' in session:
        db.session.delete(comment)
        db.session.commit()

    return redirect(safe_redirect_target(url_for('main.home')))

@bp.route('/edit_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def edit_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    comment = Comment.query.get_or_404(comment_id)
    current_user = session.get('student') or session.get('admin')

    if comment.user_id == current_user or 'admin' in session:
        new_content = request.form.get('content')
        if new_content and new_content.strip():
            comment.content = new_content.strip()
            db.session.commit()

    return redirect(safe_redirect_target(url_for('main.home')))

# =========================
# LOST & FOUND
# =========================

@bp.route('/lost_found')
def lost_found():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    page = request.args.get('page', 1, type=int)
    per_page = 12

    search_query = request.args.get('q', '').strip()
    type_filter = request.args.get('type_filter', 'All')
    category_filter = request.args.get('category_filter', 'All')
    status_filter = request.args.get('status_filter', 'All')

    query = LostItem.query
    if search_query:
        query = query.filter(or_(LostItem.item_name.ilike(f'%{search_query}%'), LostItem.description.ilike(f'%{search_query}%'), LostItem.location.ilike(f'%{search_query}%')))
    if type_filter != 'All':
        query = query.filter_by(type=type_filter)
    if category_filter != 'All':
        query = query.filter_by(category=category_filter)
    if status_filter != 'All':
        query = query.filter_by(is_resolved=(status_filter == 'Resolved'))

    pagination = query.order_by(LostItem.is_resolved.asc(), LostItem.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    items = pagination.items
    return render_template("lost_found.html", items=items, pagination=pagination, search_query=search_query, type_filter=type_filter, category_filter=category_filter, status_filter=status_filter, categories=LOST_FOUND_CATEGORIES)

@bp.route('/add_lost_item', methods=['POST'])
@require_csrf
def add_lost_item():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))
    item_type = request.form.get('type', '').strip() # Lost or Found
    item_name = request.form.get('item_name', '').strip()
    description = request.form.get('description', '').strip()
    location = request.form.get('location', '').strip()
    contact = request.form.get('contact', '').strip()
    category = request.form.get('category', '').strip()

    if item_type not in {'Lost', 'Found'} or not item_name or not location or not contact:
        flash("Please fill all required lost/found item details.")
        return redirect(url_for('main.lost_found'))

    image = request.files.get('image')
    image_filename = None
    if image and image.filename != '':
        if allowed_media_file(image.filename) and upload_content_is_safe(image):
            try:
                image_filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
                image.save(os.path.join(current_app.config['UPLOAD_FOLDER'], image_filename))
            except Exception:
                current_app.logger.exception("Unable to save lost/found item image")
                flash("Could not upload the photo. Please try again without the image.")
                return redirect(url_for('main.lost_found'))
        else:
            flash("Invalid file type. Please upload an image file.")
            return redirect(url_for('main.lost_found')) # Ensure redirect on error

    new_item = LostItem(
        type=item_type,
        item_name=item_name,
        description=description,
        location=location,
        category=category,
        contact=contact,
        image_file=image_filename,
        user_id=session['student']
    )
    db.session.add(new_item)
    db.session.commit()
    flash("Item reported successfully.")
    return redirect(url_for('main.lost_found'))

@bp.route('/resolve_item/<int:item_id>', methods=['POST'])
@require_csrf
def resolve_item(item_id):
    item = LostItem.query.get_or_404(item_id)
    if 'admin' in session or ('student' in session and session['student'] == item.user_id):
        item.is_resolved = True
        db.session.commit()
        flash("Item marked as resolved/returned.")
    return redirect(url_for('main.lost_found'))

@bp.route('/delete_lost_item/<int:item_id>', methods=['POST'])
@require_csrf
def delete_lost_item(item_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    item = LostItem.query.get_or_404(item_id)
    current_user = session.get('student') or session.get('admin')

    if item.user_id == current_user or 'admin' in session:
        if item.image_file:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], item.image_file)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        db.session.delete(item)
        db.session.commit()
        flash("Lost/Found item deleted successfully.")

    return redirect(url_for('main.lost_found'))

# =========================
# ANONYMOUS DOUBTS
# =========================

@bp.route('/doubts')
def doubts():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    doubts_list = AnonymousDoubt.query.options(
        selectinload(AnonymousDoubt.replies)
    ).order_by(AnonymousDoubt.timestamp.desc()).limit(50).all()

    author_names = {}
    if 'admin' in session:
        author_ids = {doubt.user_id for doubt in doubts_list}
        for doubt in doubts_list:
            author_ids.update(reply.user_id for reply in doubt.replies if reply.user_id != session.get('admin'))
        author_names = {
            student.student_id: student.name
            for student in Student.query.filter(Student.student_id.in_(author_ids)).all()
        } if author_ids else {}

    # Standardize name display for anonymity (Works for both Admin and Student)
    for doubt in doubts_list:
        if 'admin' in session:
            doubt.display_name = author_names.get(doubt.user_id, "Unknown Student")
        else:
            doubt.display_name = "Anonymous Student"

        for reply in doubt.replies:
            if reply.user_id == session.get('admin'):
                reply.display_name = "Admin"
            elif 'admin' in session:
                reply.display_name = author_names.get(reply.user_id, "Unknown Peer")
            else:
                reply.display_name = "Anonymous Peer"

    return render_template("doubts.html", doubts=doubts_list)

@bp.route('/add_doubt', methods=['POST'])
@require_csrf
def add_doubt():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    content = request.form.get('content')
    file = request.files.get('file')
    file_filename = None

    if file and file.filename != '':
        if allowed_file(file.filename):
            file_filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], file_filename))
        else:
            flash("Invalid file type attached.") # CRITICAL FIX: Ensure redirect on invalid file type.
            return redirect(url_for('main.doubts')) # Ensure redirect on error

    if content and content.strip():
        new_doubt = AnonymousDoubt(content=content.strip(), user_id=session['student'], file_path=file_filename)
        db.session.add(new_doubt)
        db.session.commit()
        flash("Your anonymous doubt has been posted.")
    return redirect(url_for('main.doubts'))

@bp.route('/reply_doubt/<int:doubt_id>', methods=['POST'])
@require_csrf
def reply_doubt(doubt_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    content = request.form.get('content')
    user_id = session.get('student') or session.get('admin')

    if content and content.strip():
        new_reply = DoubtReply(content=content.strip(), user_id=user_id, doubt_id=doubt_id)
        db.session.add(new_reply)

        doubt = AnonymousDoubt.query.get(doubt_id)
        if doubt and doubt.user_id != user_id:
            # Notify the doubt creator
            msg = "Someone replied to your anonymous doubt."
            notification = Notification(user_id=doubt.user_id, message=msg, type='doubt_reply')
            db.session.add(notification)

        db.session.commit()
        flash("Reply added anonymously.")
    return redirect(url_for('main.doubts'))

@bp.route('/delete_doubt/<int:doubt_id>', methods=['POST'])
@require_csrf
def delete_doubt(doubt_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    doubt = AnonymousDoubt.query.get_or_404(doubt_id)
    # Admin or the student who posted it can delete it
    if 'admin' in session or doubt.user_id == session.get('student'):
        if doubt.file_path:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], doubt.file_path)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        db.session.delete(doubt)
        db.session.commit()
        flash("Doubt deleted.")
    return redirect(url_for('main.doubts'))

@bp.route('/delete_doubt_reply/<int:reply_id>', methods=['POST'])
@require_csrf
def delete_doubt_reply(reply_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    reply = DoubtReply.query.get_or_404(reply_id)
    if 'admin' in session or reply.user_id == session.get('student'):
        db.session.delete(reply)
        db.session.commit()
        flash("Reply deleted.")
    return redirect(url_for('main.doubts'))

# =========================
# CAMPUS POLLS
# =========================

@bp.route('/polls')
def polls():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    user_id = session.get('student') or session.get('admin')
    polls_list = Poll.query.order_by(Poll.timestamp.desc()).limit(30).all()

    # Process polls to calculate percentages
    for poll in polls_list:
        # Fetch creator name
        admin_creator = Admin.query.filter_by(admin_id=poll.created_by).first()
        if admin_creator:
            poll.creator_name = "Administrator"
        else:
            student_creator = Student.query.filter_by(student_id=poll.created_by).first()
            if student_creator:
                poll.creator_name = student_creator.name
            else:
                poll.creator_name = "Unknown"

        poll.user_has_voted = PollVote.query.filter_by(poll_id=poll.id, user_id=user_id).first()
        total_votes = PollVote.query.filter_by(poll_id=poll.id).count()
        poll.total_votes = total_votes

        for option in poll.options:
            votes = PollVote.query.filter_by(option_id=option.id).all()
            option.count = len(votes)
            option.percent = int((option.count / total_votes) * 100) if total_votes > 0 else 0

            voter_ids = [v.user_id for v in votes]
            option.voters = Student.query.filter(Student.student_id.in_(voter_ids)).all() if voter_ids else []

    return render_template("polls.html", polls=polls_list)

@bp.route('/create_poll', methods=['GET', 'POST'])
@require_csrf
def create_poll():
    # Only admins or logged-in students can create
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    if request.method == 'POST':
        question = request.form.get('question')
        options_raw = request.form.getlist('options')

        # Filter empty options
        options = [opt.strip() for opt in options_raw if opt.strip()]

        if not question or len(options) < 2:
            flash("Poll must have a question and at least 2 options.")
            return render_template("create_poll.html")

        user_id = session.get('student') or session.get('admin')
        new_poll = Poll(question=question, created_by=user_id)
        db.session.add(new_poll)

        # We need to flush to get the new_poll.id before creating options
        try:
            db.session.flush()
            for opt_text in options:
                db.session.add(PollOption(text=opt_text, poll_id=new_poll.id))
            db.session.commit()
            flash("Poll created successfully!")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating poll: {e}")
            flash("An error occurred while creating the poll. Please try again.", "danger")
        return redirect(url_for('main.polls'))

    return render_template("create_poll.html")

@bp.route('/vote/<int:poll_id>/<int:option_id>', methods=['POST'])
@require_csrf
def vote(poll_id, option_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    user_id = session.get('student') or session.get('admin')

    # Do not allow a URL to associate an option from one poll with another.
    if not PollOption.query.filter_by(id=option_id, poll_id=poll_id).first():
        abort(404)

    # Check if already voted
    if PollVote.query.filter_by(poll_id=poll_id, user_id=user_id).first():
        flash("You have already voted on this poll.")
        return redirect(url_for('main.polls'))

    # Record vote
    vote = PollVote(user_id=user_id, poll_id=poll_id, option_id=option_id)
    db.session.add(vote)
    try:
        db.session.commit()

        # Send notification to the poll creator
        poll = Poll.query.get(poll_id)
        if poll and poll.created_by != user_id:
            voter_name = "Someone"
            if 'student' in session:
                student = Student.query.filter_by(student_id=user_id).first()
                if student:
                    voter_name = student.name
            msg = f"{voter_name} voted on your poll: '{poll.question[:30]}...'"
            db.session.add(Notification(user_id=poll.created_by, message=msg, type='poll_vote'))
            db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("You have already voted on this poll.")

    return redirect(url_for('main.polls'))


# =========================
# STUDENT PROJECT SHOWCASE
# =========================

@bp.route('/projects')
def projects():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    page = request.args.get('page', 1, type=int)
    per_page = 9
    search_query = request.args.get('q', '').strip()
    tech_filter = request.args.get('tech_filter', 'All')

    query = Project.query.filter(Project.user_id.isnot(None))
    if search_query:
        query = query.filter(or_(
            Project.title.ilike(f'%{search_query}%'),
            Project.description.ilike(f'%{search_query}%'),
            Project.technologies.ilike(f'%{search_query}%'),
            Project.user_name.ilike(f'%{search_query}%')
        ))
    if tech_filter != 'All':
        query = query.filter(Project.technologies.ilike(f'%{tech_filter}%'))

    pagination = query.order_by(Project.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    projects_list = pagination.items

    current_user_id = session.get('student')
    for project in projects_list:
        project.like_count = ProjectLike.query.filter_by(project_id=project.id).count()
        project.user_liked = ProjectLike.query.filter_by(user_id=current_user_id, project_id=project.id).first() is not None

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and pagination.has_next:
        # For AJAX requests, return only the grid of projects
        return render_template("_projects_grid.html", projects=projects_list)

    return render_template("projects.html", projects=projects_list, pagination=pagination, search_query=search_query, tech_filter=tech_filter, technologies=PROJECT_TECHNOLOGIES, has_next=pagination.has_next)

@bp.route('/add_project', methods=['GET', 'POST'])
@require_csrf
def add_project():
    current_app.logger.debug('add_project: session student=%s admin=%s', session.get('student'), session.get('admin'))
    if 'student' not in session and 'admin' not in session:
        current_app.logger.debug('add_project: no student or admin in session, redirecting to auth.student_login')
        return redirect(url_for('auth.student_login'))

    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        technologies = request.form.get('technologies')
        github_link = request.form.get('github_link')
        live_demo_link = request.form.get('live_demo_link')
        image = request.files.get('image')
        video = request.files.get('video')

        if not title or not description:
            flash("Title and description are required.", "warning")
            return redirect(url_for('main.add_project'))

        image_filename = None
        if image and image.filename != '':
            if allowed_media_file(image.filename) and image.filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS:
                image_filename = f"project_img_{uuid.uuid4().hex}_{secure_filename(image.filename)}"
                try:
                    dest = os.path.join(current_app.config['UPLOAD_FOLDER'], image_filename)
                    current_app.logger.debug('add_project: saving image to %s', dest)
                    image.save(dest)
                except Exception as e:
                    current_app.logger.exception('add_project: failed saving image')
                    flash('Failed to save project image. Please try again or contact admin.', 'danger')
                    return redirect(url_for('main.add_project'))
            else:
                flash("Invalid image file type.", "warning")
                return redirect(url_for('main.add_project'))

        video_filename = None
        if video and video.filename != '':
            if allowed_media_file(video.filename) and video.filename.rsplit('.', 1)[1].lower() in VIDEO_EXTENSIONS:
                video_filename = f"project_vid_{uuid.uuid4().hex}_{secure_filename(video.filename)}"
                try:
                    dest = os.path.join(current_app.config['UPLOAD_FOLDER'], video_filename)
                    current_app.logger.debug('add_project: saving video to %s', dest)
                    video.save(dest)
                except Exception as e:
                    current_app.logger.exception('add_project: failed saving video')
                    flash('Failed to save project video. Please try again or contact admin.', 'danger')
                    return redirect(url_for('main.add_project'))
            else:
                flash("Invalid video file type.", "warning")
                return redirect(url_for('main.add_project'))

        # Determine owner info: prefer student, fall back to admin
        owner_id = None
        owner_name = None
        if session.get('student'):
            student = Student.query.filter_by(student_id=session['student']).first()
            owner_name = student.name if student else session.get('student')
            owner_id = session.get('student')
        else:
            # Admin adding a project
            admin = Admin.query.filter_by(admin_id=session.get('admin')).first()
            owner_id = admin.admin_id if admin else None
            owner_name = "Admin"

        new_project = Project(
            title=title,
            description=description,
            technologies=technologies,
            image_file=image_filename,
            video_file=video_filename,
            github_link=github_link,
            live_demo_link=live_demo_link,
            user_id=owner_id,
            user_name=owner_name
        )
        db.session.add(new_project)
        db.session.commit()
        flash("Project added successfully!", "success")
        return redirect(url_for('main.projects'))

    return render_template("add_project.html", technologies=PROJECT_TECHNOLOGIES)

@bp.route('/project/<int:project_id>')
def view_project(project_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    project = Project.query.get_or_404(project_id)
    current_user_id = session.get('student')

    project.like_count = ProjectLike.query.filter_by(project_id=project.id).count()
    project.user_liked = ProjectLike.query.filter_by(user_id=current_user_id, project_id=project.id).first() is not None
    project.comments = ProjectComment.query.filter_by(project_id=project.id).order_by(ProjectComment.timestamp.asc()).all()

    return render_template("project_detail.html", project=project, current_user_id=current_user_id)

@bp.route('/like_project/<int:project_id>', methods=['POST'])
@require_csrf
def like_project(project_id):
    if 'student' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    user_id = session['student']
    existing_like = ProjectLike.query.filter_by(user_id=user_id, project_id=project_id).first()

    if existing_like:
        db.session.delete(existing_like)
    else:
        new_like = ProjectLike(user_id=user_id, project_id=project_id)
        db.session.add(new_like)

    db.session.commit()
    return jsonify({'success': True, 'likes': ProjectLike.query.filter_by(project_id=project_id).count(), 'liked': not existing_like})

@bp.route('/comment_project/<int:project_id>', methods=['POST'])
@require_csrf
def add_project_comment(project_id):
    if 'student' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    content = request.form.get('content')
    if content and content.strip():
        user_id = session['student']
        student = Student.query.filter_by(student_id=user_id).first()
        user_name = student.name if student else user_id

        comment = ProjectComment(content=content, user_id=user_id, user_name=user_name, project_id=project_id)
        db.session.add(comment)
        db.session.commit()
        return jsonify({'success': True, 'user_name': user_name, 'content': content, 'timestamp': "Just now"})
    return jsonify({'success': False})

@bp.route('/delete_project/<int:project_id>', methods=['POST'])
@require_csrf
def delete_project(project_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    project = Project.query.get_or_404(project_id)
    current_user = session.get('student') or session.get('admin')

    if project.user_id == current_user or 'admin' in session:
        remove_uploaded_media(project.image_file)
        remove_uploaded_media(project.video_file)
        db.session.delete(project)
        db.session.commit()
        flash("Project deleted successfully.", "success")
    else:
        flash("You are not authorized to delete this project.", "warning")
    return redirect(url_for('main.projects'))

@bp.route('/delete_project_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def delete_project_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    comment = ProjectComment.query.get_or_404(comment_id)
    project_id = comment.project_id
    current_user = session.get('student') or session.get('admin')

    if comment.user_id == current_user or 'admin' in session:
        db.session.delete(comment)
        db.session.commit()
        flash("Comment deleted.", "success")
    else:
        flash("You are not authorized to delete this comment.", "warning")

    return redirect(url_for('main.view_project', project_id=project_id))

@bp.route('/edit_project_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def edit_project_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    comment = ProjectComment.query.get_or_404(comment_id)
    project_id = comment.project_id
    current_user = session.get('student') or session.get('admin')

    if comment.user_id == current_user or 'admin' in session:
        new_content = request.form.get('content')
        if new_content and new_content.strip():
            comment.content = new_content.strip()
            db.session.commit()
            flash("Comment updated successfully.", "success")
    else:
        flash("You are not authorized to edit this comment.", "warning")

    return redirect(url_for('main.view_project', project_id=project_id))

# =========================
# ANONYMOUS SUGGESTION BOX
# =========================

@bp.route('/submit_suggestion', methods=['GET', 'POST'])
@require_csrf
def submit_suggestion():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    if request.method == 'POST':
        content = request.form.get('content')
        category = request.form.get('category')
        is_anonymous = 'is_anonymous' in request.form

        if not content or not category:
            flash("Suggestion content and category are required.", "warning")
            return redirect(url_for('main.submit_suggestion'))

        new_suggestion = Suggestion(
            content=content,
            category=category,
            user_id=None if is_anonymous else session['student']
        )
        db.session.add(new_suggestion)
        create_admin_notification(
            'suggestion',
            f'New anonymous suggestion received in category: {category}.',
            'main.admin_suggestions',
        )
        db.session.commit()
        flash("Your suggestion has been submitted anonymously.", "success")
        return redirect(url_for('main.home'))

    return render_template("submit_suggestion.html", categories=SUGGESTION_CATEGORIES)

@bp.route('/admin/suggestions')
def admin_suggestions():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    status_filter = request.args.get('status', 'All')
    category_filter = request.args.get('category', 'All')

    query = Suggestion.query
    if status_filter != 'All':
        query = query.filter_by(status=status_filter)
    if category_filter != 'All':
        query = query.filter_by(category=category_filter)

    suggestions = query.order_by(Suggestion.timestamp.desc()).all()
    return render_template("admin_suggestions.html", suggestions=suggestions, current_status=status_filter, current_category=category_filter, categories=SUGGESTION_CATEGORIES)

@bp.route('/admin/suggestions/<int:suggestion_id>/update', methods=['POST'])
@require_csrf
def update_suggestion_status(suggestion_id):
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    suggestion = Suggestion.query.get_or_404(suggestion_id)
    new_status = request.form.get('status')
    admin_notes = request.form.get('admin_notes')

    if new_status and new_status in ['New', 'Under Review', 'Implemented', 'Rejected']:
        suggestion.status = new_status
    if admin_notes:
        suggestion.admin_notes = admin_notes

    db.session.commit()
    flash("Suggestion updated successfully.", "success")
    return redirect(url_for('main.admin_suggestions'))

# =========================
# ADMIN LOGIN
# =========================

@bp.route('/admin')
def admin_base():
    if 'admin' in session:
        return redirect(url_for('main.admin_dashboard'))
    if 'student' in session:
        return redirect(url_for('main.home'))
    return redirect(url_for('main.admin_login'))

@bp.route('/admin/login', methods=['GET','POST'])
@require_csrf
def admin_login():
    if 'admin' in session:
        return redirect(url_for('main.admin_dashboard'))
    if 'student' in session:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        admin_id = request.form.get('admin_id', '').strip() or ''
        password = request.form.get('password', '') or ''
        try:
            return _handle_login_attempt(
                Admin, 'admin_id', admin_id, password,
                "main.admin_dashboard", "Invalid Admin Login", "admin_login.html", csrf_token
            )
        except Exception:
            current_app.logger.exception("Admin login failed unexpectedly")
            flash("An unexpected error occurred during login. Please try again later.", "danger")
            return render_template("admin_login.html", csrf_token=csrf_token), 500
    return render_template("admin_login.html", csrf_token=csrf_token)

# =========================
# ADMIN PROFILE
# =========================

@bp.route('/admin/profile')
def admin_profile():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    admin = Admin.query.filter_by(admin_id=session['admin']).first()
    if not admin:
        session.clear()
        return redirect(url_for('main.admin_login'))

    events = Event.query.filter_by(is_admin=True).order_by(Event.id.desc()).all()

    return render_template("admin_profile.html", admin=admin, events=events)


# =========================
# ADMIN DASHBOARD
# =========================

@bp.route('/admin/dashboard')
def admin_dashboard():

    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    student_count = Student.query.count()
    event_count = Event.query.count()
    allowed_count = AllowedStudent.query.count()
    pending_report_count = Report.query.filter(Report.status != 'Resolved').count()
    unread_feedback_count = AdminNotification.query.filter_by(category='feedback', is_read=False).count()


    # Events by Department
    dept_stats = db.session.query(Event.department, func.count(Event.id)).group_by(Event.department).all()
    dept_labels = [d[0] for d in dept_stats]
    dept_data = [d[1] for d in dept_stats]

    # Top Liked Events
    top_events = db.session.query(Event.title, func.count(EventLike.id).label('likes'))\
        .join(EventLike, Event.id == EventLike.event_id)\
        .group_by(Event.id)\
        .order_by(func.count(EventLike.id).desc())\
        .limit(5).all()

    # Student Search Logic
    student_q = request.args.get('student_q')
    if student_q:
        filters = [
            Student.name.ilike(f'%{student_q}%'),
            Student.student_id.ilike(f'%{student_q}%'),
            Student.department.ilike(f'%{student_q}%')
        ]
        # Add graduation year to search if query is a number
        if student_q.isdigit():
            filters.append(Student.graduation_year == int(student_q))

        students = Student.query.filter(or_(*filters)).all()
        events = Event.query.filter(or_(Event.title.ilike(f'%{student_q}%'), Event.posted_by.ilike(f'%{student_q}%'))).all()
    else:
        students = Student.query.order_by(Student.id.desc()).limit(50).all()
        events = Event.query.order_by(Event.id.desc()).limit(10).all()

    return render_template("admin_dashboard.html", events=events, student_count=student_count,
                           event_count=event_count, allowed_count=allowed_count,
                           pending_report_count=pending_report_count,
                           unread_feedback_count=unread_feedback_count, dept_labels=dept_labels,
                           dept_data=dept_data, top_events=top_events, students=students, # This line is less likely
                           student_q=student_q)


@bp.route('/admin/notifications')
def admin_notifications():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    notifications = AdminNotification.query.order_by(AdminNotification.timestamp.desc()).limit(100).all()
    AdminNotification.query.filter_by(is_read=False).update({'is_read': True}, synchronize_session=False)
    db.session.commit()
    clear_nav_count_cache()
    return render_template('admin_notifications.html', notifications=notifications)


@bp.route('/admin/recovery-requests')
def admin_recovery_requests():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    recovery_requests = RecoveryRequest.query.order_by(
        (RecoveryRequest.status == 'Pending').desc(), RecoveryRequest.created_at.desc()
    ).all()
    return render_template('admin_recovery_requests.html', recovery_requests=recovery_requests)


@bp.route('/admin/recovery-requests/<int:request_id>/issue-link', methods=['POST'])
@require_csrf
def issue_admin_recovery_link(request_id):
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    recovery_request = RecoveryRequest.query.get_or_404(request_id)
    student = Student.query.filter_by(student_id=recovery_request.student_id).first()
    if not student:
        flash('No registered student account was found for this recovery request.', 'warning')
        return redirect(url_for('main.admin_recovery_requests'))

    temporary_password = f"AU{secrets.token_urlsafe(9)}9"
    student.password = generate_password_hash(temporary_password)
    recovery_request.status = 'Temporary password issued'
    recovery_request.reviewed_by = session['admin']
    recovery_request.reviewed_at = datetime.now()
    db.session.commit()

    emailed = False
    recipient_email = (recovery_request.recovery_email or student.email or '').strip()
    if recipient_email:
        try:
            mail.send(Message(
                subject='AU Daily temporary password',
                recipients=[recipient_email],
                html=render_template(
                    'admin_temp_password_email.html',
                    name=student.name,
                    temporary_password=temporary_password,
                ),
            ))
            emailed = True
        except Exception:
            app.logger.exception('Unable to send administrator-issued temporary password email')

    return render_template('admin_recovery_link.html', recovery_request=recovery_request,
                           student=student, temporary_password=temporary_password,
                           recipient_email=recipient_email, emailed=emailed)


@bp.route('/admin/feedback')
def admin_feedback():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    # Fetch all feedback and link it to the student who submitted it
    feedbacks = db.session.query(Feedback, Student.name, Student.department)\
        .outerjoin(Student, Feedback.user_id == Student.student_id)\
        .order_by(Feedback.timestamp.desc()).all()

    return render_template("admin_feedback.html", feedbacks=feedbacks)


@bp.route('/admin/feedback/<int:id>/reply', methods=['POST'])
@require_csrf
def reply_to_feedback(id):
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    reply = request.form.get('reply', '').strip()
    feedback = Feedback.query.get_or_404(id)
    if not reply:
        flash('Please write a reply before sending it.', 'warning')
        return redirect(url_for('main.admin_feedback'))
    feedback.admin_response = reply
    feedback.responded_at = datetime.now()
    db.session.commit()
    notify_student_of_admin_reply(feedback.user_id, reply, 'AU Daily: reply to your feedback', 'feedback')
    flash('Reply sent to the student.')
    return redirect(url_for('main.admin_feedback'))

@bp.route('/admin/reports')
def admin_reports():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    status = request.args.get('status', '').strip()
    report_type = request.args.get('type', '').strip()
    query = Report.query
    if status:
        query = query.filter_by(status=status)
    if report_type:
        query = query.filter_by(report_type=report_type)
    reports = query.order_by(Report.timestamp.desc()).all()
    for report in reports:
        report.duplicate_count = (Report.query.filter_by(item_type=report.item_type, item_id=report.item_id)
                                  .filter(Report.item_type.isnot(None), Report.item_id.isnot(None)).count())
    return render_template("admin_reports.html", reports=reports, current_status=status, current_type=report_type)


@bp.route('/admin/reports/<int:id>/reply', methods=['POST'])
@require_csrf
def reply_to_report(id):
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    reply = request.form.get('reply', '').strip()
    report = Report.query.get_or_404(id)
    if not report.user_id:
        flash('Anonymous reports cannot receive an admin reply.', 'warning')
        return redirect(url_for('main.admin_reports'))
    if not reply:
        flash('Please write a reply before sending it.', 'warning')
        return redirect(url_for('main.admin_reports'))
    report.admin_response = reply
    report.responded_at = datetime.now()
    db.session.commit()
    notify_student_of_admin_reply(report.user_id, reply, 'AU Daily: reply to your report', 'report')
    flash('Reply sent to the student.')
    return redirect(url_for('main.admin_reports'))


@bp.route('/admin/reports/<int:id>/status', methods=['POST'])
@require_csrf
def update_report_status(id):
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    status = request.form.get('status', '')
    if status not in {'Pending', 'In Progress', 'Resolved'}:
        flash('Invalid report status.', 'warning')
        return redirect(url_for('main.admin_reports'))
    report = Report.query.get_or_404(id)
    report.status = status
    db.session.commit()
    flash('Report status updated.')
    return redirect(url_for('main.admin_reports'))


@bp.route('/admin/reports/<int:id>/action', methods=['POST'])
@require_csrf
def action_report(id):
    """Delete a reported item only when its type is known to the application."""
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    report = Report.query.get_or_404(id)
    if request.form.get('action') != 'delete_post':
        flash('Unsupported report action.', 'warning')
        return redirect(url_for('main.admin_reports'))

    models = {'Event': Event, 'NewsPost': NewsPost, 'JobPost': JobPost}
    target_model = models.get(report.item_type)
    target = target_model.query.get(report.item_id) if target_model and report.item_id else None
    if not target:
        flash('The reported item is no longer available.', 'warning')
        return redirect(url_for('main.admin_reports'))

    db.session.delete(target)
    report.status = 'Resolved'
    db.session.commit()
    flash('Reported item deleted and report resolved.')
    return redirect(url_for('main.admin_reports'))

@bp.route('/admin/resolve_report/<int:report_id>', methods=['POST'])
@require_csrf
def resolve_report(report_id):
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    report = Report.query.get_or_404(report_id)
    report.status = 'Resolved'
    db.session.commit()
    flash("Report marked as resolved.")
    return redirect(url_for('main.admin_reports'))

@bp.route('/admin/export_students')
def export_students():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    students = Student.query.all()

    # Create a string buffer
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(['Student ID', 'Name', 'Department', 'Graduation Year', 'Email', 'Phone'])

    # Write data
    def csv_cell(value):
        value = '' if value is None else str(value)
        # Prevent spreadsheet programs from interpreting student-entered values as formulas.
        return f"'{value}" if value.startswith(('=', '+', '-', '@')) else value

    for student in students:
        writer.writerow([csv_cell(student.student_id), csv_cell(student.name), csv_cell(student.department),
                         csv_cell(student.graduation_year), csv_cell(student.email), csv_cell(student.phone)])

    # Create response
    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=registered_students.csv"}
    )

@bp.route('/admin/upload_allowed_students', methods=['GET', 'POST'])
@require_csrf
def upload_allowed_students():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    if request.method == 'GET':
        flash('Use the Upload CSV button on this page to import allowed student IDs.', 'info')
        return redirect(url_for('main.view_allowed_students'))

    if 'file' not in request.files:
        flash('No CSV file was selected.', 'warning')
        return redirect(url_for('main.view_allowed_students'))

    file = request.files['file']
    if file.filename == '':
        flash('No CSV file was selected.', 'warning')
        return redirect(url_for('main.view_allowed_students'))

    if file and file.filename.lower().endswith('.csv'):
        # Save to a temporary path first to avoid overwriting the main file on a partial upload
        temp_csv_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"temp_{uuid.uuid4().hex}.csv")
        try:
            file.save(temp_csv_path)
        except Exception as e:
            flash(f"Error saving file: {e}") # This path is less likely
            current_app.logger.exception('upload_allowed_students: error saving file')
            return redirect(url_for('main.view_allowed_students'))
        # Check for Excel file disguised as CSV by checking the original stream
        file.stream.seek(0)
        if file.stream.read(2) == b'PK':
            flash("Error: The uploaded file appears to be an Excel .xlsx file. Please save it as a 'CSV (Comma delimited)' file.", "danger")
            try:
                os.remove(temp_csv_path)
            except OSError:
                pass
            return redirect(url_for('main.view_allowed_students'))
        file.stream.seek(0) # Reset stream position

        # Run update logic (same as update_allowed_ids.py)
        # We try multiple encodings because CSV files saved on different OSes (Windows/Mac) use different encodings
        new_ids = set()
        encodings = ['utf-8-sig', 'cp1252', 'latin-1']
        read_error = None

        # Check for Excel file disguised as CSV
        # 'PK' is the magic number (file signature) for ZIP archives, which .xlsx files are based on
        try:
            with open(temp_csv_path, 'rb') as f:
                if f.read(2) == b'PK':
                    flash("Error: The uploaded file appears to be an Excel .xlsx file saved with .csv extension. Please save as CSV (Comma delimited).")
                    os.remove(temp_csv_path)
                    return redirect(url_for('main.view_allowed_students'))
        except OSError:
            pass

        for encoding in encodings:
            current_app.logger.debug('upload_allowed_students: trying encoding %s', encoding)
            try:
                with open(temp_csv_path, 'r', encoding=encoding, newline='') as f:
                    reader = csv.reader(f)
                    ids_from_this_encoding = set()
                    row_count = 0
                    for row in reader:
                        row_count += 1
                        if row and len(row) > 0:
                            potential_id = normalize_allowed_student_id(row[0])
                            if potential_id:
                                ids_from_this_encoding.add(potential_id)
                if ids_from_this_encoding:
                    new_ids = ids_from_this_encoding
                    current_app.logger.debug('upload_allowed_students: parsed %d ids with encoding %s', len(new_ids), encoding)
                    break # Successfully parsed, exit the loop
                if row_count > 0:
                    read_error = "The CSV was read, but no valid student IDs were found. Ensure IDs are in the first column, not just a header."
                    break

            except UnicodeDecodeError:
                continue # Try next encoding
            except (PermissionError, IOError) as e:
                read_error = f"Could not read the file. Please check permissions or if it's open elsewhere. Error: {e}"
                break # A file system error is fatal
            except (UnicodeDecodeError, csv.Error):
                continue # If parsing fails, try the next encoding

        if not new_ids:
            # Use the specific error if we have one, otherwise a generic one.
            os.remove(temp_csv_path)
            if read_error:
                flash(read_error)
            else:
                flash("Error: Could not read IDs from CSV. The file might be empty or have an unsupported encoding.")
            return redirect(url_for('main.view_allowed_students'))

        # Compare with existing IDs in the database
        existing_ids = {s.student_id for s in AllowedStudent.query.all()}
        current_app.logger.debug('upload_allowed_students: existing_ids count=%d', len(existing_ids))
        ids_to_add = new_ids - existing_ids

        added_count = 0
        if ids_to_add:
            for student_id in sorted(list(ids_to_add)):
                db.session.add(AllowedStudent(student_id=student_id))
            added_count = len(ids_to_add)
        current_app.logger.debug('upload_allowed_students: committing %d new ids', added_count)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            os.remove(temp_csv_path)
            current_app.logger.exception("Failed to commit new allowed students")
            flash(f"Database error: {e}", "danger")
            return redirect(url_for('main.view_allowed_students'))

        main_csv_path = os.path.join(current_app.root_path, 'allowed_students.csv')
        try:
            os.replace(temp_csv_path, main_csv_path)
        except OSError:
            current_app.logger.exception("Database updated, but allowed_students.csv could not be replaced")
            try:
                os.remove(temp_csv_path)
            except OSError:
                pass
            flash("IDs were saved in the database, but the CSV file could not be updated. Close the CSV if it is open and try again.", "warning")
            return redirect(url_for('main.view_allowed_students'))

        if added_count > 0:
            flash(f"Success! {added_count} new student IDs were added to the whitelist.", "success")
        else:
            flash("All student IDs from the CSV are already in the database. No new IDs were added.", "info")
    else:
        flash('Invalid file type. Please upload a CSV file.')

    return redirect(url_for('main.view_allowed_students'))

@bp.route('/admin/allowed_students')
def view_allowed_students():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    page = request.args.get('page', 1, type=int)
    search_q = request.args.get('q', '')

    query = AllowedStudent.query
    if search_q:
        query = query.filter(AllowedStudent.student_id.ilike(f'%{search_q}%'))

    pagination = query.order_by(AllowedStudent.student_id).paginate(page=page, per_page=50, error_out=False)
    allowed_students = pagination.items

    return render_template("allowed_students_list.html", allowed_students=allowed_students, pagination=pagination, search_q=search_q)

@bp.route('/admin/add_allowed_student', methods=['GET', 'POST'])
@require_csrf
def add_allowed_student():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    if request.method == 'GET':
        flash('Use the Add ID button on this page to add a student ID.', 'info')
        return redirect(url_for('main.view_allowed_students'))

    student_id = normalize_allowed_student_id(request.form.get('student_id'))
    if student_id:
        if not AllowedStudent.query.filter_by(student_id=student_id).first():
            db.session.add(AllowedStudent(student_id=student_id))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash(f"Student ID {student_id} is already allowed.", "info")
                return redirect(url_for('main.view_allowed_students'))

            csv_path = os.path.join(current_app.root_path, 'allowed_students.csv')
            try:
                with open(csv_path, 'a', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([student_id])
            except OSError:
                current_app.logger.exception("Could not append allowed student ID to CSV")
                flash(f"Student ID {student_id} was added, but the CSV file could not be updated.", "warning")
                return redirect(url_for('main.view_allowed_students'))
            flash(f"Student ID {student_id} added successfully.", "success")
        else:
            flash(f"Student ID {student_id} is already allowed.", "info")
    else:
        flash("Please enter a valid student ID.", "warning")

    return redirect(url_for('main.view_allowed_students'))

@bp.route('/admin/delete_allowed_student/<int:id>', methods=['POST'])
@require_csrf
def delete_allowed_student(id):
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    student = AllowedStudent.query.get_or_404(id)
    s_id = student.student_id
    db.session.delete(student)
    db.session.commit()

    # Attempt to remove from CSV to maintain consistency
    csv_path = os.path.join(current_app.root_path, 'allowed_students.csv')
    if os.path.exists(csv_path):
        try:
            lines = []
            encodings = ['utf-8-sig', 'cp1252', 'latin-1']
            for encoding in encodings:
                try:
                    with open(csv_path, 'r', encoding=encoding, newline='') as f:
                        lines = f.readlines()
                    break
                except UnicodeDecodeError:
                    continue

            if lines:
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    for line in lines:
                        parts = line.strip().split()
                        if not parts or parts[0] != s_id:
                            f.write(line)
        except Exception:
            pass

    flash(f"ID {s_id} removed from allowed list.")
    return redirect(url_for('main.view_allowed_students'))

@bp.route('/admin/delete_allowed_students_bulk', methods=['POST'])
@require_csrf
def delete_allowed_students_bulk():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    ids_to_delete = request.form.getlist('student_ids')
    if not ids_to_delete:
        flash("No students selected for deletion.")
        return redirect(url_for('main.view_allowed_students'))

    # Fetch objects to get the actual student_id strings (for CSV removal)
    students = AllowedStudent.query.filter(AllowedStudent.id.in_(ids_to_delete)).all()
    student_id_strings = {s.student_id for s in students}

    # Delete from DB
    for student in students:
        db.session.delete(student)
    db.session.commit()

    # Update CSV
    csv_path = os.path.join(current_app.root_path, 'allowed_students.csv')
    if os.path.exists(csv_path) and student_id_strings:
        try:
            lines = []
            encodings = ['utf-8-sig', 'cp1252', 'latin-1']
            for encoding in encodings:
                try:
                    with open(csv_path, 'r', encoding=encoding, newline='') as f:
                        lines = f.readlines()
                    break
                except UnicodeDecodeError:
                    continue

            if lines:
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    for line in lines:
                        parts = line.strip().split()
                        # If the line's ID is NOT in our deletion set, keep it
                        if not parts or parts[0] not in student_id_strings:
                            f.write(line)
        except Exception:
            pass

    flash(f"{len(students)} allowed IDs removed.")
    return redirect(url_for('main.view_allowed_students'))

# =========================
# ADD EVENT
# =========================

@bp.route('/add_event', methods=['GET','POST'])
@require_csrf
def add_event():

    if 'admin' not in session and 'student' not in session:
        return redirect(url_for('auth.student_login'))

    if request.method == "POST":

        title = request.form['title']
        description = request.form['description']
        date = request.form['date']
        department = request.form['department']

        # Handle Image Upload
        image = request.files.get('image')
        image_filename = None
        if image and image.filename != '':
            image_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
            if allowed_media_file(image.filename) and image.filename.rsplit('.', 1)[1].lower() in image_extensions:
                image_filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
                image.save(os.path.join(current_app.config['UPLOAD_FOLDER'], image_filename))
            else:
                flash("Invalid file type. Please upload an image or video.")
                return redirect(url_for('main.add_event')) # Ensure redirect on error

        is_admin_post = False
        posted_by_name = "Unknown"
        user_id = None

        if 'admin' in session:
            is_admin_post = True
            posted_by_name = "Admin"
            user_id = session['admin']
        elif 'student' in session:
            student = Student.query.filter_by(student_id=session['student']).first()
            posted_by_name = student.name if student else session['student']
            user_id = session['student']

        event = Event(
            title=title,
            description=description,
            date=date,
            department=department,
            is_admin=is_admin_post,
            posted_by=posted_by_name,
            user_id=user_id,
            image_file=image_filename
        )

        db.session.add(event)
        db.session.commit()
        flash("Event added successfully!")

        # Optimized Notification Logic
        if department == 'General':
            recipients = Student.query.all()
        else:
            recipients = Student.query.filter_by(department=department).all()

        for student in recipients:
            msg = f"New {department} Alert: {title}"
            db.session.add(Notification(user_id=student.student_id, message=msg, type='new_event', event_id=event.id))
        db.session.commit()

        if 'admin' in session:
            return redirect(url_for('main.admin_dashboard'))
        else:
            return redirect(url_for('main.home'))

    return render_template("add_event.html", departments=DEPARTMENTS)

@bp.route('/edit_event/<int:event_id>', methods=['GET', 'POST'])
@require_csrf
def edit_event(event_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    event = Event.query.get_or_404(event_id)

    # Authorization Check
    if 'student' in session:
        student = Student.query.filter_by(student_id=session['student']).first()
        # Users can only edit events they posted (check by ID)
        if not student or event.user_id != student.student_id:
            flash("You are not authorized to edit this event.")
            return redirect(url_for('main.home'))

    if request.method == 'POST':
        event.title = request.form['title']
        event.description = request.form['description']
        event.date = request.form['date']
        event.department = request.form['department']

        image = request.files.get('image')
        if image and image.filename != '':
            if allowed_media_file(image.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
                image.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                event.image_file = filename
            else:
                flash("Invalid file type.")
                return redirect(request.url)

        db.session.commit()
        flash("Event updated successfully!")

        if 'admin' in session:
            return redirect(url_for('main.admin_dashboard'))
        else:
            return redirect(url_for('main.student_profile'))

    return render_template("edit_event.html", event=event, departments=DEPARTMENTS)

@bp.route('/edit_event_description/<int:event_id>', methods=['POST'])
@require_csrf
def edit_event_description(event_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    event = Event.query.get_or_404(event_id)

    # Authorization Check
    if 'student' in session:
        student = Student.query.filter_by(student_id=session['student']).first()
        if not student or event.user_id != student.student_id:
            flash("You are not authorized to edit this event.")
            return redirect(url_for('main.home'))

    new_desc = request.form.get('description')
    if new_desc and new_desc.strip():
        event.description = new_desc.strip()
        db.session.commit()

    return redirect(safe_redirect_target(url_for('main.home')))

# =========================
# DELETE EVENT
# =========================

@bp.route('/delete_event/<int:id>', methods=['POST'])
@require_csrf
def delete_event(id):

    if 'admin' not in session and 'student' not in session:
        return redirect(url_for('auth.student_login'))

    event = Event.query.get_or_404(id)

    # Authorization Check
    if 'student' in session:
        # Users can only delete events they posted (check by ID)
        if event.user_id != session['student']:
            flash("You are not authorized to delete this event.")
            return redirect(url_for('main.home'))

    remove_uploaded_media(event.image_file)
    db.session.delete(event)
    db.session.commit()
    flash("Event deleted successfully.")

    return redirect(safe_redirect_target(url_for('main.home')))


@bp.route('/student/phone-recovery', methods=['GET', 'POST'])
@require_csrf
def phone_recovery():
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        mobile = normalize_indian_mobile(request.form.get('phone', ''))
        student = Student.query.filter_by(student_id=student_id).first() if student_id else None
        registered_mobile = normalize_indian_mobile(student.phone) if student else None

        if not student or not mobile or mobile != registered_mobile:
            flash('The Student ID and registered mobile number do not match our records.', 'warning')
            return redirect(url_for('main.phone_recovery'))
        if not current_app.config.get('FAST2SMS_API_KEY') or not current_app.config.get('FAST2SMS_OTP_ID'):
            flash('Phone recovery is temporarily unavailable. Please contact the administrator.', 'warning')
            return redirect(url_for('main.phone_recovery'))

        now = datetime.now()
        attempt = PhoneRecoveryAttempt.query.filter_by(student_id=student.student_id).first()
        if not attempt:
            attempt = PhoneRecoveryAttempt(student_id=student.student_id, window_started_at=now)
            db.session.add(attempt)
        if attempt.locked_until and attempt.locked_until > now:
            flash('Too many incorrect codes. Please wait 15 minutes before trying again.', 'warning')
            return redirect(url_for('main.phone_recovery'))
        if attempt.last_sent_at and now - attempt.last_sent_at < timedelta(minutes=1):
            flash('Please wait one minute before requesting another OTP.', 'warning')
            return redirect(url_for('main.phone_recovery'))
        if not attempt.window_started_at or now - attempt.window_started_at >= timedelta(minutes=15):
            attempt.window_started_at, attempt.send_count, attempt.failed_verifications = now, 0, 0
        if attempt.send_count >= 3:
            attempt.locked_until = now + timedelta(minutes=15)
            db.session.commit()
            flash('Too many OTP requests. Please wait 15 minutes before trying again.', 'warning')
            return redirect(url_for('main.phone_recovery'))

        result = fast2sms_otp_request('send', {'otp_id': current_app.config['FAST2SMS_OTP_ID'], 'mobile': mobile})
        if not result.get('return'):
            flash('We could not send an OTP right now. Please try again later.', 'warning')
            return redirect(url_for('main.phone_recovery'))
        attempt.last_sent_at = now
        attempt.send_count += 1
        db.session.commit()
        session['phone_recovery_student_id'] = student.student_id
        session['phone_recovery_mobile'] = mobile
        session.pop('phone_recovery_verified', None)
        flash('OTP sent to your registered mobile number.')
        return redirect(url_for('main.verify_phone_recovery'))

    return render_template('phone_recovery.html', configured=bool(current_app.config.get('FAST2SMS_API_KEY') and current_app.config.get('FAST2SMS_OTP_ID')))


@bp.route('/student/phone-recovery/verify', methods=['GET', 'POST'])
@require_csrf
def verify_phone_recovery():
    student_id = session.get('phone_recovery_student_id')
    mobile = session.get('phone_recovery_mobile')
    if not student_id or not mobile:
        flash('Start phone recovery again to receive a new OTP.', 'warning') # This path is less likely
        return redirect(url_for('main.phone_recovery'))

    if request.method == 'POST':
        otp = re.sub(r'\D', '', request.form.get('otp', ''))
        attempt = PhoneRecoveryAttempt.query.filter_by(student_id=student_id).first()
        now = datetime.now()
        if not attempt or (attempt.locked_until and attempt.locked_until > now):
            flash('This recovery request is locked or expired. Start again later.', 'warning')
            return redirect(url_for('main.phone_recovery'))
        if len(otp) < 4:
            flash('Enter the OTP sent to your mobile number.', 'warning')
            return redirect(url_for('main.verify_phone_recovery'))
        result = fast2sms_otp_request('verify', {'mobile': mobile, 'otp': otp})
        if not result.get('return'):
            attempt.failed_verifications += 1
            if attempt.failed_verifications >= 5:
                attempt.locked_until = now + timedelta(minutes=15)
            db.session.commit()
            flash('Invalid OTP. Please try again.', 'warning') # This path is less likely
            return redirect(url_for('main.verify_phone_recovery'))
        attempt.failed_verifications = 0
        db.session.commit()
        session['phone_recovery_verified'] = True
        return redirect(url_for('main.reset_password_by_phone'))

    return render_template('verify_phone_otp.html', mobile=f'******{mobile[-4:]}')


@bp.route('/student/phone-recovery/reset', methods=['GET', 'POST'])
@require_csrf
def reset_password_by_phone():
    student_id = session.get('phone_recovery_student_id')
    if not student_id or not session.get('phone_recovery_verified'):
        flash('Verify your phone OTP before resetting the password.', 'warning')
        return redirect(url_for('main.phone_recovery'))
    student = Student.query.filter_by(student_id=student_id).first()
    if not student:
        session.pop('phone_recovery_student_id', None)
        session.pop('phone_recovery_mobile', None)
        session.pop('phone_recovery_verified', None)
        return redirect(url_for('main.phone_recovery'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirmation = request.form.get('confirm_password', '')
        if not valid_password(password):
            flash('Your new password must be at least 10 characters and include letters and numbers.', 'warning')
        elif password != confirmation:
            flash('The passwords do not match.', 'warning')
        else:
            student.password = generate_password_hash(password)
            PhoneRecoveryAttempt.query.filter_by(student_id=student_id).delete()
            db.session.commit()
            session.pop('phone_recovery_student_id', None)
            session.pop('phone_recovery_mobile', None)
            session.pop('phone_recovery_verified', None)
            flash('Password updated. You can now sign in.')
            return redirect(url_for('auth.student_login'))
    return render_template('phone_reset_password.html')


# =========================
# STUDENT PROFILE
# =========================

@bp.route('/profile/<string:student_id>')
def view_profile(student_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    student = Student.query.filter_by(student_id=student_id).first()

    if not student:
        admin = Admin.query.filter_by(admin_id=student_id).first()
        if not admin and student_id not in ["None", "Admin", "admin"]:
            flash("Profile not found.")
            return redirect(safe_redirect_target(url_for('main.home')))

        class MockAdmin:
            def __init__(self):
                self.student_id = admin.admin_id if admin else "Admin"
                self.name = "Admin"
                self.department = "University Administration"
                self.graduation_year = "Staff"
                self.profile_pic = None
                self.is_admin_profile = True
        student = MockAdmin()

    current_user_id = session.get('student')

    # Get stats
    follower_count = Follower.query.filter_by(followed_id=student.student_id).count()
    following_count = Follower.query.filter_by(follower_id=student.student_id).count()

    # Check if current user is following this profile
    is_following = False
    if current_user_id and current_user_id != student.student_id:
        is_following = Follower.query.filter_by(follower_id=current_user_id, followed_id=student.student_id).first() is not None

    # Get user's content
    events = Event.query.filter_by(user_id=student.student_id).order_by(Event.id.desc()).all()
    news_posts = NewsPost.query.filter_by(user_id=student.student_id).order_by(NewsPost.timestamp.desc()).all()

    # Get user's skills and endorsement data
    skills = StudentSkill.query.filter_by(student_id=student_id).all()
    for skill in skills:
        skill.endorsement_count = SkillEndorsement.query.filter_by(skill_id=skill.id).count()
        if current_user_id:
            skill.user_has_endorsed = SkillEndorsement.query.filter_by(
                skill_id=skill.id,
                endorser_student_id=current_user_id
            ).first() is not None
        else:
            skill.user_has_endorsed = False

    return render_template("view_profile.html",
                           student=student,
                           events=events,
                           news_posts=news_posts,
                           follower_count=follower_count,
                           following_count=following_count,
                           is_following=is_following,
                           current_user_id=current_user_id,
                           skills=skills)

@bp.route('/student/dashboard')
def student_dashboard():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    student_id = session['student']
    student = Student.query.filter_by(student_id=student_id).first()
    if not student:
        session.clear()
        return redirect(url_for('auth.student_login'))

    events_registered = EventRegistration.query.filter_by(user_id=student_id).count()
    polls_voted = PollVote.query.filter_by(user_id=student_id).count()
    doubts_asked = AnonymousDoubt.query.filter_by(user_id=student_id).count()
    doubts_replied = DoubtReply.query.filter_by(user_id=student_id).count()
    total_tasks = Task.query.filter_by(user_id=student_id).count()
    completed_tasks = Task.query.filter_by(user_id=student_id, is_completed=True).count()
    pending_tasks = max(total_tasks - completed_tasks, 0)

    chart_labels = []
    chart_tasks = []
    current_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for offset in range(5, -1, -1):
        month_seed = current_month - timedelta(days=offset * 31)
        month_start = month_seed.replace(day=1)
        next_month = datetime(month_start.year + (month_start.month // 12), (month_start.month % 12) + 1, 1)
        chart_labels.append(month_start.strftime('%b'))
        chart_tasks.append(
            Task.query.filter(
                Task.user_id == student_id,
                Task.timestamp >= month_start,
                Task.timestamp < next_month
            ).count()
        )

    return render_template("student_dashboard.html",
                           student=student,
                           events_registered=events_registered,
                           polls_voted=polls_voted,
                           doubts_asked=doubts_asked,
                           doubts_replied=doubts_replied,
                           total_tasks=total_tasks,
                           completed_tasks=completed_tasks,
                           pending_tasks=pending_tasks,
                           chart_labels=chart_labels,
                           chart_tasks=chart_tasks)

@bp.route('/api/user_preview/<string:student_id>')
def user_preview(student_id):
    if 'student' not in session and 'admin' not in session:
        return "", 401

    student = Student.query.filter_by(student_id=student_id).first()

    if not student:
        admin = Admin.query.filter_by(admin_id=student_id).first()
        if not admin and student_id not in ["None", "Admin", "admin"]:
            return ""

        class MockAdmin:
            def __init__(self):
                self.student_id = admin.admin_id if admin else "Admin"
                self.name = "Administrator"
                self.department = "University Administration"
                self.profile_pic = None
                self.is_admin_profile = True
        student = MockAdmin()

    pic = student.profile_pic or 'default.jpg'
    html = f"""
    <div class="text-center">
        <img src="/static/media/{pic}" class="rounded-circle shadow-sm mb-2 border" style="width: 70px; height: 70px; object-fit: cover;">
        <h6 class="fw-bold mb-1 text-truncate">{escape(student.name or '')}</h6>
        <p class="small text-muted mb-3"><span class="badge bg-light text-dark border">{escape(student.department)}</span></p>
        <a href="/profile/{student.student_id}" class="btn btn-sm btn-primary rounded-pill px-4">View Profile</a>
    </div>
    """
    return html

@bp.route('/student/profile')
def student_profile():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    # Redirect to the new generic profile view for the logged-in user
    return redirect(url_for('main.view_profile', student_id=session['student']))

@bp.route('/profile/<string:student_id>/<string:list_type>')
def followers_list(student_id, list_type):
    if 'student' not in session and 'admin' not in session:
        flash("Please log in to view this page.")
        return redirect(url_for('auth.student_login'))

    user = Student.query.filter_by(student_id=student_id).first()
    if not user:
        admin = Admin.query.filter_by(admin_id=student_id).first()
        if not admin and student_id not in ["None", "Admin", "admin"]:
            flash("Profile not found.")
            return redirect(safe_redirect_target(url_for('main.home')))

        class MockAdmin:
            def __init__(self):
                self.student_id = admin.admin_id if admin else "Admin"
                self.name = "Admin"
                self.profile_pic = None
                self.is_admin_profile = True
        user = MockAdmin()

    page = request.args.get('page', 1, type=int)
    per_page = 10 # You can adjust this number

    search_query = request.args.get('q', '').strip()

    if list_type == 'followers':
        user_ids = db.session.query(Follower.follower_id).filter_by(followed_id=student_id).all()
        title = "Followers"
    elif list_type == 'following':
        user_ids = db.session.query(Follower.followed_id).filter_by(follower_id=student_id).all()
        title = "Following"
    else:
        flash("Invalid list type.")
        return redirect(url_for('main.home'))

    ids = [u[0] for u in user_ids]
    # Start with a base query for students whose IDs are in the 'ids' list
    users_query = Student.query.filter(Student.student_id.in_(ids)) if ids else Student.query.filter(False)

    if search_query:
        users_query = users_query.filter(or_(Student.name.ilike(f'%{search_query}%'), Student.student_id.ilike(f'%{search_query}%')))

    # Apply pagination
    pagination = users_query.order_by(Student.name).paginate(page=page, per_page=per_page, error_out=False)
    users_list = pagination.items

    current_user_id = session.get('student')
    if current_user_id:
        for u in users_list:
            u.is_self = (u.student_id == current_user_id)
            if not u.is_self:
                u.is_following = Follower.query.filter_by(follower_id=current_user_id, followed_id=u.student_id).first() is not None
    return render_template("followers.html", users_list=users_list, title=title, main_user=user, search_query=search_query, pagination=pagination)

@bp.route('/student/settings', methods=['GET', 'POST'])
@require_csrf
def student_settings():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    student = Student.query.filter_by(student_id=session['student']).first()
    if not student:
        session.clear()
        return redirect(url_for('auth.student_login'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_info':
            new_email = request.form.get('email')
            # Check uniqueness if email changed
            department = request.form.get('department')
            if new_email != student.email and Student.query.filter_by(email=new_email).first():
                flash("Email already in use by another account.")
            else:
                # Safely convert graduation_year to integer
                grad_year_str = request.form.get('graduation_year')
                graduation_year = None
                if grad_year_str and grad_year_str.isdigit():
                    graduation_year = int(grad_year_str)

                student.name = request.form.get('name')
                student.email = new_email
                student.phone = request.form.get('phone')
                student.graduation_year = graduation_year
                if department in DEPARTMENTS:
                    student.department = department
                db.session.commit()
                flash("Profile information updated successfully.")

        elif action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')

            if not check_password_hash(student.password, current_password):
                flash("Incorrect current password.")
            elif not valid_password(new_password):
                flash("New passwords must be at least 10 characters and include letters and numbers.")
            elif new_password != confirm_password:
                flash("New passwords do not match.")
            else:
                student.password = generate_password_hash(new_password)
                db.session.commit()
                flash("Password changed successfully.")

        elif action == 'add_skill':
            skill_name = request.form.get('skill_name', '').strip()
            if skill_name and not StudentSkill.query.filter_by(student_id=student.student_id, skill_name=skill_name).first():
                db.session.add(StudentSkill(student_id=student.student_id, skill_name=skill_name))
                db.session.commit()
                flash(f"Skill '{skill_name}' added.")

        return redirect(url_for('main.student_settings'))

    return render_template("student_settings.html", student=student, departments=DEPARTMENTS)

@bp.route('/student/update_pic', methods=['POST'])
@require_csrf
def update_profile_pic():
    wants_json = request.accept_mimetypes.best == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if 'student' not in session:
        if wants_json:
            return jsonify(success=False, message="Please sign in again."), 401
        return redirect(url_for('auth.student_login'))

    student = Student.query.filter_by(student_id=session['student']).first()
    if not student:
        flash("Profile not found.")
        if wants_json:
            return jsonify(success=False, message="Profile not found."), 404 # This path is less likely
        return redirect(url_for('main.home'))

    image = request.files.get('profile_pic')

    if image and image.filename != '':
        image_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if allowed_media_file(image.filename) and image.filename.rsplit('.', 1)[1].lower() in image_extensions:
            # Generate clean filename with extension
            ext = image.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            new_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            old_filename = student.profile_pic
            try:
                image.save(new_file_path)
                student.profile_pic = filename
                db.session.commit()
            except Exception:
                db.session.rollback()
                if os.path.exists(new_file_path):
                    try:
                        os.remove(new_file_path)
                    except OSError:
                        pass
                current_app.logger.exception("Profile picture update failed")
                if wants_json:
                    return jsonify(success=False, message="Could not save the photo. Please try a smaller JPG or PNG image."), 500
                flash("Could not save the photo. Please try a smaller JPG or PNG image.")
                return redirect(safe_redirect_target(url_for('main.student_settings')))

            if old_filename: # This block was correctly indented in a previous step, but seems to have been reverted.
                old_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], old_filename)
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                    except OSError:
                        pass
            flash("Profile picture updated successfully!")
            if wants_json:
                return jsonify(success=True, message="Profile picture updated successfully.")
        else:
            flash("Invalid file type. Please use JPG, PNG, GIF, or WEBP.")
            if wants_json:
                return jsonify(success=False, message="Please choose a JPG, PNG, GIF, or WEBP image."), 400
    else:
        if wants_json:
            return jsonify(success=False, message="Please select an image file first."), 400
        flash("Please select an image file first.") # This line was also misaligned.

    return redirect(safe_redirect_target(url_for('main.student_settings')))

@bp.route('/student/remove_pic', methods=['POST'])
@require_csrf
def remove_profile_pic():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    student = Student.query.filter_by(student_id=session['student']).first()
    if student.profile_pic:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], student.profile_pic)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        student.profile_pic = None
        db.session.commit()
        flash("Profile picture removed.")

    return redirect(safe_redirect_target(url_for('main.student_settings')))

@bp.route('/follow/<string:student_id>', methods=['GET','POST'])
@require_csrf
def follow_user(student_id):
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    if request.method == 'GET':
        flash("To follow a user, please click the 'Follow' or 'Unfollow' button on their profile.", "info")
        return redirect(safe_redirect_target(url_for('main.view_profile', student_id=student_id)))

    current_user_id = session['student']
    if current_user_id == student_id:
        flash("You cannot follow yourself.")
        return redirect(safe_redirect_target(url_for('main.view_profile', student_id=student_id)))

    existing_follow = Follower.query.filter_by(follower_id=current_user_id, followed_id=student_id).first()

    if existing_follow:
        db.session.delete(existing_follow)
        flash(f"You have unfollowed this user.")
    else:
        # Create a notification for the user who is being followed
        follower = Student.query.filter_by(student_id=current_user_id).first()
        if follower:
            notification_message = f"**{follower.name}** started following you."
            new_notification = Notification(user_id=student_id, message=notification_message, type='new_follower')
            db.session.add(new_notification)

        new_follow = Follower(follower_id=current_user_id, followed_id=student_id)
        db.session.add(new_follow)
        flash(f"You are now following this user.")

    db.session.commit()
    return redirect(safe_redirect_target(url_for('main.view_profile', student_id=student_id)))

@bp.route('/delete_skill/<int:skill_id>', methods=['POST'])
@require_csrf
def delete_skill(skill_id):
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    skill = StudentSkill.query.get_or_404(skill_id)
    if skill.student_id == session['student']:
        db.session.delete(skill)
        db.session.commit()
        flash("Skill removed from your profile.")
    else:
        flash("You are not authorized to remove this skill.")

    return redirect(url_for('main.student_settings'))

@bp.route('/endorse_skill/<int:skill_id>', methods=['POST'])
@require_csrf
def endorse_skill(skill_id):
    if 'student' not in session:
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        return redirect(url_for('auth.student_login'))

    endorser_id = session['student']
    skill_to_endorse = StudentSkill.query.get_or_404(skill_id)

    if endorser_id == skill_to_endorse.student_id:
        if request.accept_mimetypes.best != 'application/json':
            flash("You cannot endorse your own skills.")
            return redirect(safe_redirect_target(url_for('main.skill_exchange_hub')))
        return jsonify({'success': False, 'error': 'You cannot endorse your own skills.'}), 403

    existing_endorsement = SkillEndorsement.query.filter_by(skill_id=skill_id, endorser_student_id=endorser_id).first()

    if existing_endorsement:
        db.session.delete(existing_endorsement)
        db.session.commit()
        new_count = SkillEndorsement.query.filter_by(skill_id=skill_id).count()
        if request.accept_mimetypes.best != 'application/json':
            flash("Skill endorsement removed.")
            return redirect(safe_redirect_target(url_for('main.skill_exchange_hub')))
        return jsonify({'success': True, 'endorsed': False, 'count': new_count})
    else:
        new_endorsement = SkillEndorsement(skill_id=skill_id, endorser_student_id=endorser_id)
        db.session.add(new_endorsement)
        db.session.commit()
        new_count = SkillEndorsement.query.filter_by(skill_id=skill_id).count()
        if request.accept_mimetypes.best != 'application/json':
            flash("Skill endorsed successfully.")
            return redirect(safe_redirect_target(url_for('main.skill_exchange_hub')))
        return jsonify({'success': True, 'endorsed': True, 'count': new_count})

@bp.route('/api/skill_endorsers/<int:skill_id>')
def get_skill_endorsers(skill_id):
    endorsements = SkillEndorsement.query.filter_by(skill_id=skill_id).all()
    endorser_ids = [e.endorser_student_id for e in endorsements]
    endorsers = Student.query.filter(Student.student_id.in_(endorser_ids)).all()
    return render_template('_endorsers_list.html', endorsers=endorsers)

@bp.route('/skill-exchange')
def skill_exchange_hub():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    search_query = request.args.get('q', '').strip()
    department_filter = request.args.get('department', 'All').strip() or 'All'
    page = request.args.get('page', 1, type=int)
    per_page = 12

    query = db.session.query(StudentSkill, Student).join(
        Student, StudentSkill.student_id == Student.student_id
    )

    if search_query:
        search_filter = f'%{search_query}%'
        query = query.filter(or_(
            StudentSkill.skill_name.ilike(search_filter),
            Student.name.ilike(search_filter),
            Student.student_id.ilike(search_filter),
            Student.department.ilike(search_filter),
        ))

    if department_filter != 'All':
        query = query.filter(Student.department == department_filter)

    pagination = query.order_by(StudentSkill.skill_name.asc(), Student.name.asc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    current_user_id = session.get('student')
    skill_cards = []
    for skill, student in pagination.items:
        endorsement_count = SkillEndorsement.query.filter_by(skill_id=skill.id).count()
        user_has_endorsed = False
        if current_user_id:
            user_has_endorsed = SkillEndorsement.query.filter_by(
                skill_id=skill.id,
                endorser_student_id=current_user_id,
            ).first() is not None

        skill_cards.append({
            'skill': skill,
            'student': student,
            'endorsement_count': endorsement_count,
            'user_has_endorsed': user_has_endorsed,
        })

    popular_skills = db.session.query(
        StudentSkill.skill_name,
        func.count(StudentSkill.id).label('student_count'),
    ).group_by(StudentSkill.skill_name).order_by(func.count(StudentSkill.id).desc()).limit(8).all()

    return render_template(
        'skill_exchange.html',
        skill_cards=skill_cards,
        pagination=pagination,
        search_query=search_query,
        department_filter=department_filter,
        departments=DEPARTMENTS,
        popular_skills=popular_skills,
        current_user_id=current_user_id,
    )

@bp.route('/notices')
def notice_board():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    dept_filter = request.args.get('department', 'All')
    query = Notice.query

    if dept_filter != 'All':
        query = query.filter_by(department=dept_filter)

    notices = query.order_by(Notice.is_urgent.desc(), Notice.timestamp.desc()).limit(100).all()

    # Create a list of unique departments from notices for the filter dropdown
    notice_departments = db.session.query(Notice.department).distinct().all()
    filter_depts = sorted(['All'] + [d[0] for d in notice_departments])

    return render_template("notice_board.html", notices=notices, filter_depts=filter_depts, current_dept=dept_filter)

@bp.route('/admin/manage_notices', methods=['GET', 'POST'])
@require_csrf
def admin_manage_notices():
    if 'admin' not in session:
        return redirect(url_for('main.admin_login'))

    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        department = request.form.get('department')
        is_urgent = 'is_urgent' in request.form
        file = request.files.get('file')
        file_filename = None

        if not title or not department:
            flash("Title and Department are required.", "warning")
            return redirect(url_for('main.admin_manage_notices'))

        if file and file.filename != '':
            if allowed_file(file.filename):
                file_filename = f"notice_{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], file_filename))
            else:
                flash("Invalid file type for attachment.", "warning")
                return redirect(url_for('main.admin_manage_notices'))

        new_notice = Notice(
            title=title,
            content=content,
            department=department,
            is_urgent=is_urgent,
            file_path=file_filename,
            posted_by_admin_id=session['admin']
        )
        db.session.add(new_notice)
        db.session.commit()
        flash("Notice posted successfully.", "success")
        return redirect(url_for('main.admin_manage_notices'))

    # For GET request
    notices = Notice.query.order_by(Notice.timestamp.desc()).limit(100).all()
    # Add 'General' and 'Exam Section' to the list of departments for the form
    form_departments = sorted(list(set(DEPARTMENTS + ['General', 'Exam Section'])))
    return render_template("admin_manage_notices.html", notices=notices, departments=form_departments)

@bp.route('/feedback', methods=['GET', 'POST'])
@require_csrf
def feedback():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    if request.method == 'POST':
        content = request.form.get('content')
        if content and content.strip():
            new_feedback = Feedback(user_id=session['student'], content=content)
            db.session.add(new_feedback)
            create_admin_notification(
                'feedback',
                f'New feedback from student {session["student"]}.',
                'main.admin_feedback',
            )
            db.session.commit()
            send_admin_alert(
                'AU Daily: new student feedback',
                'New student feedback',
                {'Student ID': session['student'], 'Feedback': content.strip()},
            )
            flash("Thank you! Your feedback has been submitted.")
            return redirect(url_for('main.home'))
        else:
            flash("Please write something before submitting.")

    return render_template("feedback.html")

@bp.route('/submit_report', methods=['GET', 'POST'])
@require_csrf
def submit_report():
    if 'student' not in session:
        # Handle AJAX request for unauthenticated user
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, error="Authentication required", redirect_url=url_for('auth.student_login')), 401
        # Handle regular request
        return redirect(url_for('auth.student_login'))

    if request.method == 'GET':
        return render_template('submit_report.html')

    report_type = request.form.get('report_type')
    description = request.form.get('description')
    item_type = (request.form.get('item_type') or '').strip() or None
    item_id_raw = (request.form.get('item_id') or '').strip()
    item_id = int(item_id_raw) if item_id_raw.isdigit() else None
    screenshot = request.files.get('screenshot')
    screenshot_filename = None
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    valid_report_types = {'Spam', 'Fake Job', 'Abuse', 'Bug', 'Other'}
    if report_type in valid_report_types and description and description.strip():
        if screenshot and screenshot.filename != '':
            if allowed_media_file(screenshot.filename) and screenshot.filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS:
                screenshot_filename = f"{uuid.uuid4().hex}_{secure_filename(screenshot.filename)}"
                try:
                    screenshot.save(os.path.join(current_app.config['UPLOAD_FOLDER'], screenshot_filename))
                except Exception as e:
                    current_app.logger.error(f"Report screenshot save failed: {e}")
                    if is_ajax: return jsonify(success=False, message="Could not save screenshot."), 500
                    flash("Could not save screenshot. Please try again.")
                    return redirect(safe_redirect_target(url_for('main.home')))
            else:
                flash("Invalid screenshot file type.")

        new_report = Report(
            user_id=None if request.form.get('is_anonymous') else session['student'],
            report_type=report_type,
            description=description.strip(),
            item_type=item_type,
            item_id=item_id,
            image_file=screenshot_filename
        )
        db.session.add(new_report)
        create_admin_notification(
            'report',
            f'New {report_type.lower()} report from {"an anonymous student" if new_report.user_id is None else "student " + session["student"]}.',
            'main.admin_reports',
        )
        db.session.commit()
        send_admin_alert(
            f'AU Daily: new {report_type.lower()} report',
            'New student report',
            {
                'Report type': report_type,
                'Student ID': 'Anonymous' if new_report.user_id is None else session['student'],
                'Description': description.strip(),
                'Reported from': request.referrer or 'AU Daily',
            },
        )
        flash("Report submitted successfully. Admins will review it.")
        if is_ajax:
            return jsonify(success=True, message="Report submitted successfully.")
    else:
        flash('Please select an issue type and describe the problem.', 'warning')
        if is_ajax:
            return jsonify(success=False, message="Please select an issue type and describe the problem."), 400

    return redirect(request.referrer or url_for('main.home'))

# =========================
# PRIVATE MESSAGING
# =========================

@bp.route('/messages')
def inbox():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    current_user = session['student']

    messages = PrivateMessage.query.filter(
        or_(PrivateMessage.sender_id == current_user, PrivateMessage.receiver_id == current_user)
    ).order_by(PrivateMessage.timestamp.desc()).limit(200).all()

    other_user_ids = {
        msg.receiver_id if msg.sender_id == current_user else msg.sender_id
        for msg in messages
    }
    students_by_id = {
        student.student_id: student
        for student in Student.query.filter(Student.student_id.in_(other_user_ids)).all()
    } if other_user_ids else {}

    unread_counts = {
        sender_id: count
        for sender_id, count in db.session.query(
            PrivateMessage.sender_id,
            func.count(PrivateMessage.id)
        ).filter(
            PrivateMessage.receiver_id == current_user,
            PrivateMessage.is_read.is_(False),
            PrivateMessage.sender_id.in_(other_user_ids)
        ).group_by(PrivateMessage.sender_id).all()
    } if other_user_ids else {}

    conversations = {}
    for msg in messages:
        other_user_id = msg.receiver_id if msg.sender_id == current_user else msg.sender_id
        if other_user_id not in conversations:
            other_student = students_by_id.get(other_user_id)
            if other_student:
                conversations[other_user_id] = {
                    'user': other_student,
                    'latest_msg': msg,
                    'unread_count': unread_counts.get(other_user_id, 0)
                }

    return render_template("inbox.html", conversations=conversations.values())

@bp.route('/chat/<string:student_id>', methods=['GET', 'POST'])
@require_csrf
def chat(student_id):
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    current_user = session['student']
    if current_user == student_id:
        flash("You cannot chat with yourself.")
        return redirect(url_for('main.inbox'))

    other_user = Student.query.filter_by(student_id=student_id).first_or_404()

    # Handle Sending New Message
    if request.method == 'POST':
        content = request.form.get('content', '')
        image = request.files.get('image')
        image_filename = None

        if image and image.filename != '':
            if allowed_media_file(image.filename):
                image_filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
                image.save(os.path.join(current_app.config['UPLOAD_FOLDER'], image_filename))

        if content.strip() or image_filename:
            new_msg = PrivateMessage(sender_id=current_user, receiver_id=student_id, content=content.strip(), image_file=image_filename)
            db.session.add(new_msg)
            db.session.commit()
            clear_nav_count_cache()
            return redirect(url_for('main.chat', student_id=student_id))

    # Mark unread messages as read when opening chat
    unread_updated = PrivateMessage.query.filter_by(
        sender_id=student_id,
        receiver_id=current_user,
        is_read=False
    ).update({'is_read': True}, synchronize_session=False)
    if unread_updated:
        db.session.commit()
        clear_nav_count_cache()

    # Get Chat History
    messages = PrivateMessage.query.filter(
        or_(
            (PrivateMessage.sender_id == current_user) & (PrivateMessage.receiver_id == student_id),
            (PrivateMessage.sender_id == student_id) & (PrivateMessage.receiver_id == current_user)
        )
    ).order_by(PrivateMessage.timestamp.desc()).limit(150).all()
    messages.reverse()

    return render_template("chat.html", other_user=other_user, messages=messages, current_user=current_user)

@bp.route('/delete_message/<int:message_id>', methods=['POST'])
@require_csrf
def delete_message(message_id):
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    msg = PrivateMessage.query.get_or_404(message_id)
    if msg.sender_id == session['student']:
        if msg.image_file:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], msg.image_file)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        db.session.delete(msg)
        db.session.commit()

    return redirect(safe_redirect_target(url_for('main.inbox')))

# =========================
# LOGOUT
# =========================

# =========================
# STUDENT UTILITIES (CALCULATOR)
# =========================

@bp.route('/gpa_calculator')
def gpa_calculator():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))
    return render_template("gpa_calculator.html")

@bp.route('/planner')
def planner():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    tasks = Task.query.filter_by(user_id=session['student']).order_by(
        Task.is_completed.asc(),
        Task.timestamp.desc()
    ).limit(100).all()
    return render_template("planner.html", tasks=tasks)

@bp.route('/add_task', methods=['POST'])
@require_csrf
def add_task():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    task_content = request.form.get('task')
    due_date = request.form.get('due_date') # Can be empty

    if task_content and task_content.strip():
        new_task = Task(
            task=task_content.strip(),
            due_date=due_date if due_date else None,
            user_id=session['student']
        )
        db.session.add(new_task)
        db.session.commit()
    return redirect(url_for('main.planner'))

@bp.route('/toggle_task/<int:task_id>', methods=['POST'])
@require_csrf
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    if 'student' in session and task.user_id == session['student']:
        task.is_completed = not task.is_completed
        db.session.commit()
    return redirect(url_for('main.planner'))

@bp.route('/delete_task/<int:task_id>', methods=['POST'])
@require_csrf
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    if 'student' in session and task.user_id == session['student']:
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for('main.planner'))

# =========================
# ACADEMIC RESOURCES HUB
# =========================

@bp.route('/resources')
def resources():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    search_query = request.args.get('q', '').strip()
    dept_filter = request.args.get('department')
    year_filter = request.args.get('year')
    my_dept_filter = request.args.get('my_department')

    page = request.args.get('page', 1, type=int)
    per_page = 12

    query = Resource.query
    if search_query:
        query = query.filter(
            or_(
                Resource.title.ilike(f'%{search_query}%'),
                Resource.subject.ilike(f'%{search_query}%')
            )
        )
    if dept_filter:
        query = query.filter_by(department=dept_filter)
    if year_filter:
        query = query.filter_by(year=year_filter)
    if my_dept_filter and 'student' in session:
        student = Student.query.filter_by(student_id=session['student']).first()
        if student and student.department:
            query = query.filter_by(department=student.department)


    pagination = query.order_by(Resource.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    resources_list = pagination.items

    saved_resource_ids = []
    if 'student' in session:
        saved_resource_ids = [sr.resource_id for sr in SavedResource.query.filter_by(user_id=session['student']).all()]

    return render_template(
        "resources.html",
        resources=resources_list,
        pagination=pagination,
        departments=DEPARTMENTS,
        saved_resource_ids=saved_resource_ids
    )

@bp.route('/add_resource', methods=['POST'])
@require_csrf
def add_resource():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    title = request.form.get('title')
    subject = request.form.get('subject')
    department = request.form.get('department')
    year = request.form.get('year')
    file = request.files.get('file')

    # Validation
    if not all([title, subject, department, year]) or not title.strip() or not subject.strip():
        flash("All fields (Title, Subject, Dept, Year) are required.")
        return redirect(url_for('main.resources'))
    if department not in DEPARTMENTS or year not in {'1st Year', '2nd Year', '3rd Year', '4th Year', 'All Years'}:
        flash("Choose a valid department and year.")
        return redirect(url_for('main.resources'))

    if not file or file.filename == '':
        flash("No file selected for upload. Please choose a file.")
        return redirect(url_for('main.resources'))

    if file:
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else None

        if ext and ext in current_app.config['RESOURCE_EXTENSIONS']:
            try:
                # Generate unique, safe filename
                safe_name = secure_filename(file.filename) or f"resource_{uuid.uuid4().hex[:8]}.{ext}"
                unique_filename = f"{uuid.uuid4().hex}_{safe_name}"

                # Ensure directory exists
                os.makedirs(current_app.config['RESOURCE_FOLDER'], exist_ok=True)

                # The file_path in the DB should only be the filename. The full path is constructed in the template.
                file.save(os.path.join(current_app.config['RESOURCE_FOLDER'], unique_filename))

                user_id = session.get('student') or session.get('admin')
                user_name = "Admin"
                if 'student' in session:
                    student = Student.query.filter_by(student_id=user_id).first()
                    if student:
                        user_name = student.name

                new_resource = Resource(
                    title=title,
                    subject=subject,
                    department=department,
                    year=year,
                    file_path=unique_filename,
                    user_id=user_id,
                    user_name=user_name
                )
                db.session.add(new_resource)
                db.session.commit()
                flash("Resource uploaded successfully!")
            except Exception as e:
                db.session.rollback()
                print(f"ERROR: Resource upload failed: {e}")
                flash(f"Upload failed: {str(e)}")
                return redirect(url_for('main.resources')) # Ensure redirect on error
        else:
            flash(f"Invalid file format (.{ext if ext else 'None'}). Allowed: {', '.join(current_app.config['RESOURCE_EXTENSIONS'])}")
            return redirect(url_for('main.resources')) # Ensure redirect on error

    # This final redirect is crucial. It tells the browser the process is complete.
    return redirect(url_for('main.resources'))

@bp.route('/delete_resource/<int:resource_id>', methods=['POST'])
@require_csrf
def delete_resource(resource_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    resource = Resource.query.get_or_404(resource_id)
    current_user = session.get('student') or session.get('admin')

    if resource.user_id == current_user or 'admin' in session:
        file_path = os.path.join(app.config['RESOURCE_FOLDER'], resource.file_path)
        if not os.path.isfile(file_path):
            file_path = os.path.join(current_app.config['LEGACY_RESOURCE_FOLDER'], os.path.basename(resource.file_path))
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        db.session.delete(resource)
        db.session.commit()
        flash("Resource deleted.")

    return redirect(url_for('main.resources'))

@bp.route('/resource/<int:resource_id>/file')
def download_resource_file(resource_id):
    """Serve academic resources only to signed-in campus users."""
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))
    resource = Resource.query.get_or_404(resource_id)
    filename = os.path.basename(resource.file_path)
    folder = current_app.config['RESOURCE_FOLDER']
    if not os.path.isfile(os.path.join(folder, filename)):
        folder = current_app.config['LEGACY_RESOURCE_FOLDER']
    if not os.path.isfile(os.path.join(folder, filename)):
        abort(404)
    return send_from_directory(folder, filename, as_attachment=request.args.get('download') == '1')


@bp.route('/resource/<int:resource_id>', methods=['GET', 'POST'])
@require_csrf
def view_resource(resource_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    resource = Resource.query.get_or_404(resource_id)

    if request.method == 'POST':
        content = request.form.get('content')
        if content and content.strip():
            user_id = session.get('student') or session.get('admin')
            user_name = "Admin"
            if 'student' in session:
                student = Student.query.filter_by(student_id=user_id).first()
                user_name = student.name if student else "User"

            comment = ResourceComment(content=content.strip(), user_id=user_id, user_name=user_name, resource_id=resource_id)
            db.session.add(comment)
            db.session.commit()
            flash("Comment added!") # This path is less likely
            return redirect(url_for('main.view_resource', resource_id=resource_id))

    comments = ResourceComment.query.filter_by(resource_id=resource_id).order_by(ResourceComment.timestamp.desc()).all()
    return render_template("resource_detail.html", resource=resource, comments=comments)

@bp.route('/delete_resource_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def delete_resource_comment(comment_id):
    comment = ResourceComment.query.get_or_404(comment_id)
    if 'admin' in session or session.get('student') == comment.user_id:
        db.session.delete(comment)
        db.session.commit()
        flash("Comment deleted.")
    return redirect(safe_redirect_target(url_for('main.resources')))

@bp.route('/toggle_save_resource/<int:resource_id>', methods=['POST'])
@require_csrf
def toggle_save_resource(resource_id):
    if 'student' not in session:
        flash("Please log in to save resources.")
        return redirect(url_for('auth.student_login'))

    user_id = session['student']
    existing_save = SavedResource.query.filter_by(user_id=user_id, resource_id=resource_id).first()

    if existing_save:
        db.session.delete(existing_save)
        flash("Resource removed from bookmarks.")
    else:
        new_save = SavedResource(user_id=user_id, resource_id=resource_id)
        db.session.add(new_save)
        flash("Resource saved to bookmarks!")

    db.session.commit()
    return redirect(safe_redirect_target(url_for('main.resources')))

@bp.route('/saved_resources')
def saved_resources():
    if 'student' not in session:
        return redirect(url_for('auth.student_login'))

    user_id = session['student']
    saved_ids = [sr.resource_id for sr in SavedResource.query.filter_by(user_id=user_id).all()]
    resources_list = Resource.query.filter(Resource.id.in_(saved_ids)).all() if saved_ids else []

    return render_template("saved_resources.html", resources=resources_list)

# =========================
# CAMPUS GALLERY
# =========================

@bp.route('/gallery')
def gallery():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    gallery_items = []

    def get_media_type(filename):
        if not filename: return None
        if '.' not in filename: return None
        ext = filename.rsplit('.', 1)[1].lower()
        if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
            return 'image'
        elif ext in {'mp4', 'mov', 'avi', 'webm'}:
            return 'video'
        return None

    # 1. Fetch from Events
    events = Event.query.filter(Event.image_file.isnot(None)).all()
    for e in events:
        m_type = get_media_type(e.image_file)
        if m_type:
            gallery_items.append({
                'src': e.image_file,
                'caption': e.title,
                'user': e.posted_by,
                'user_id': e.user_id,
                'date_obj': datetime.strptime(e.date, '%Y-%m-%d') if isinstance(e.date, str) else e.date,
                'type': 'Event',
                'media_type': m_type
            })

    # 2. Fetch from News Feed
    news = NewsPost.query.filter(NewsPost.image_file.isnot(None)).all()
    for n in news:
        m_type = get_media_type(n.image_file)
        if m_type:
            gallery_items.append({
                'src': n.image_file,
                'caption': n.content,
                'user': n.user_name,
                'user_id': n.user_id,
                'date_obj': n.timestamp,
                'type': 'News',
                'media_type': m_type
            })

    # Sort by date (newest first)
    gallery_items.sort(key=lambda x: x['date_obj'], reverse=True)

    return render_template("gallery.html", images=gallery_items)

# =========================
# CAREER / OPPORTUNITIES
# =========================

@bp.route('/opportunities')
def opportunities():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    category_filter = request.args.get('category')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    query = JobPost.query
    if category_filter:
        query = query.filter_by(category=category_filter)

    pagination = query.order_by(JobPost.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    jobs = pagination.items

    return render_template("opportunities.html", jobs=jobs, pagination=pagination, categories=JOB_CATEGORIES, current_category=category_filter)

@bp.route('/add_opportunity', methods=['POST'])
@require_csrf
def add_opportunity():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    title = request.form.get('title')
    company = request.form.get('company')
    category = request.form.get('category')
    description = request.form.get('description')
    link = request.form.get('link')
    image = request.files.get('image')

    if title and category:
        if category not in JOB_CATEGORIES:
            flash("Choose a valid opportunity category.")
            return redirect(url_for('main.opportunities'))
        if not valid_external_url(link):
            flash("The opportunity link must be a complete http:// or https:// URL.")
            return redirect(url_for('main.opportunities'))
        user_id = session.get('student') or session.get('admin')
        user_name = "Admin"
        if 'student' in session:
            student = Student.query.filter_by(student_id=user_id).first()
            if student:
                user_name = student.name

        image_filename = None
        if image and image.filename != '':
            if allowed_media_file(image.filename):
                image_filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
                image.save(os.path.join(current_app.config['UPLOAD_FOLDER'], image_filename))
            else:
                flash("Invalid file type for opportunity image. Only images and videos are allowed.")
                return redirect(url_for('main.opportunities')) # Ensure redirect on error

        new_job = JobPost(
            title=title.strip(),
            company=company.strip() if company else None,
            category=category,
            description=description.strip() if description else None,
            link=link.strip() if link else None,
            image_file=image_filename, # Save the filename
            user_id=user_id,
            user_name=user_name
        )
        db.session.add(new_job)
        db.session.commit()
        flash("Opportunity posted successfully!")
    else:
        flash("Title and category are required.")

    return redirect(url_for('main.opportunities'))

@bp.route('/delete_opportunity/<int:job_id>', methods=['POST'])
@require_csrf
def delete_opportunity(job_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    job = JobPost.query.get_or_404(job_id)
    current_user = session.get('student') or session.get('admin')

    if job.user_id == current_user or 'admin' in session:
        remove_uploaded_media(job.image_file)
        db.session.delete(job)
        db.session.commit()
        flash("Opportunity deleted.")

    return redirect(url_for('main.opportunities'))

# =========================
# GLOBAL SEARCH
# =========================

@bp.route('/search')
def global_search():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('auth.student_login'))

    query = request.args.get('q', '').strip()
    if not query:
        return redirect(safe_redirect_target(url_for('main.home')))

    # Define a common search filter
    search_filter = f'%{query}%'

    # Search across Events (Title, Description, Department)
    events = Event.query.filter(
        or_(Event.title.ilike(search_filter), Event.description.ilike(search_filter), Event.department.ilike(search_filter))
    ).order_by(Event.id.desc()).limit(20).all()

    # Search across News Feed content
    news = NewsPost.query.filter(NewsPost.content.ilike(search_filter)).order_by(NewsPost.timestamp.desc()).limit(20).all()

    # Search for Students (Profiles)
    students = Student.query.filter(
        or_(Student.name.ilike(search_filter), Student.student_id.ilike(search_filter), Student.department.ilike(search_filter))
    ).limit(20).all()

    skills = db.session.query(StudentSkill, Student).join(
        Student, StudentSkill.student_id == Student.student_id
    ).filter(or_(
        StudentSkill.skill_name.ilike(search_filter),
        Student.name.ilike(search_filter),
        Student.department.ilike(search_filter),
    )).limit(20).all()

    # Search across Projects
    projects = Project.query.filter(
        or_(Project.title.ilike(search_filter), Project.description.ilike(search_filter), Project.technologies.ilike(search_filter))
    ).order_by(Project.timestamp.desc()).limit(20).all()

    # Search across Resources
    resources = Resource.query.filter(
        or_(Resource.title.ilike(search_filter), Resource.subject.ilike(search_filter))
    ).order_by(Resource.timestamp.desc()).limit(20).all()

    # Search across Opportunities
    opportunities = JobPost.query.filter(
        or_(JobPost.title.ilike(search_filter), JobPost.company.ilike(search_filter), JobPost.description.ilike(search_filter))
    ).order_by(JobPost.timestamp.desc()).limit(20).all()

    # Search across Lost & Found
    lost_and_found = LostItem.query.filter(
        or_(LostItem.item_name.ilike(search_filter), LostItem.description.ilike(search_filter), LostItem.location.ilike(search_filter))
    ).order_by(LostItem.timestamp.desc()).limit(20).all()

    total_results = len(events) + len(news) + len(students) + len(skills) + len(projects) + len(resources) + len(opportunities) + len(lost_and_found)

    return render_template("search_results.html", query=query, events=events, news=news, students=students,
                           skills=skills, projects=projects, resources=resources,
                           opportunities=opportunities, lost_and_found=lost_and_found,
                           total_results=total_results)

# =========================
# STATIC PAGES
# =========================

@bp.route('/privacy')
def privacy_policy():
    return render_template("privacy_policy.html")

@bp.route('/offline.html')
def offline_page():
    return render_template("offline.html")

@bp.route('/stream')
def stream():
    return ("", 204)


# =========================
# API FOR MOBILE APP
# =========================

@api_bp.before_request
def require_api_auth():
    # For a real mobile app, you would use token-based auth (e.g., JWT).
    # For now, we'll rely on the existing session for simplicity.
    if 'student' not in session and 'admin' not in session:
        abort(401, description="Authentication required.")

@api_bp.route('/events', methods=['GET'])
def api_get_events():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    events_query = Event.query.order_by(Event.id.desc())
    pagination = events_query.paginate(page=page, per_page=per_page, error_out=False)
    events = pagination.items

    return jsonify({
        'page': pagination.page,
        'pages': pagination.pages,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
        'events': [
            {
                'id': event.id,
                'title': event.title,
                'description': event.description,
                'date': event.date,
                'department': event.department,
                'posted_by': event.posted_by,
                'image_url': url_for('static', filename='media/' + event.image_file, _external=True) if event.image_file else None
            } for event in events
        ]
    })

@api_bp.route('/news', methods=['GET'])
def api_get_news():
    posts = NewsPost.query.order_by(NewsPost.timestamp.desc()).limit(20).all()
    return jsonify([
        {
            'id': post.id,
            'content': post.content,
            'user_name': post.user_name,
            'user_id': post.user_id,
            'timestamp': post.timestamp.isoformat(),
            'image_url': url_for('static', filename='media/' + post.image_file, _external=True) if post.image_file else None,
            'like_count': post.likes.count()
        } for post in posts
    ])


# =========================
# APPLICATION FACTORY
# =========================

def create_app(config_object=None):
    app = Flask(__name__)
    import logging
    log_level_name = os.getenv("LOG_LEVEL", "INFO" if not is_production else "WARNING").upper()
    app.logger.setLevel(getattr(logging, log_level_name, logging.INFO))

    # --- CONFIGURATION ---
    trusted_proxy_count = int(os.getenv("TRUST_PROXY_COUNT", "0"))
    if trusted_proxy_count:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_proxy_count, x_proto=trusted_proxy_count, x_host=trusted_proxy_count)

    secret_key = os.getenv("SECRET_KEY")
    if not secret_key:
        if is_production:
            raise RuntimeError("SECRET_KEY must be configured before starting in production.")
        secret_key = secrets.token_urlsafe(48)
        app.logger.warning("SECRET_KEY is not set; using a temporary development-only key.")
    app.secret_key = secret_key

    config_object = config_object or {}
    db_url = (
        config_object.get("SQLALCHEMY_DATABASE_URI")
        or os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_DATABASE_URI")
        or ""
    ).strip()
    if not db_url:
        if is_production:
            raise RuntimeError("FATAL ERROR: DATABASE_URL not found in .env file.")

        db_url = local_sqlite_url(app)
        app.logger.warning(
            "DATABASE_URL is not set; using a local SQLite database for development."
        )
    else:
        db_url = development_database_url(app, db_url)

    public_base_url = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    if public_base_url:
        parsed_public_url = urlparse(public_base_url)
        if parsed_public_url.scheme not in {"http", "https"} or not parsed_public_url.netloc:
            raise RuntimeError("PUBLIC_BASE_URL must be a complete http(s) URL.")
    elif is_production:
        raise RuntimeError("PUBLIC_BASE_URL must be configured before starting in production.")

    # ==========================
    # MAIL & APP CONFIG
    # ==========================
    app.config.update(
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "true").lower() in {"1", "true", "yes"},
        MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_USERNAME"),

        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_production,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),

        PUBLIC_BASE_URL=public_base_url, # This line is less likely
        ADMIN_ALERT_RECIPIENT=os.getenv("ADMIN_ALERT_RECIPIENT", "mahaboosubhanishaik124@gmail.com"),

        FAST2SMS_API_KEY=os.getenv("FAST2SMS_API_KEY"),
        FAST2SMS_OTP_ID=os.getenv("FAST2SMS_OTP_ID"),

        SQLALCHEMY_DATABASE_URI=db_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        UPLOAD_FOLDER=os.path.join(app.root_path, "static", "media"),
        RESOURCE_FOLDER=os.path.join(app.root_path, "private_uploads", "resources"),
        LEGACY_RESOURCE_FOLDER=os.path.join(app.root_path, "static", "media", "resources"),
        CSS_FOLDER=os.path.join(app.root_path, "static", "css"),

        ALLOWED_EXTENSIONS={
            "png", "jpg", "jpeg", "gif", "webp", "heic",
            "mp4", "mov", "avi", "webm",
            "pdf", "docx", "doc", "pptx", "ppt", "txt"
        },

        RESOURCE_EXTENSIONS={
            "pdf", "docx", "doc", "pptx", "ppt", "txt"
        },

        RESUME_EXTENSIONS={
            "pdf", "docx", "txt"
        },

        MAX_CONTENT_LENGTH=64 * 1024 * 1024,
    )
    app.config.update(config_object)

    if is_production:
        app.config["PREFERRED_URL_SCHEME"] = "https"
        app.config["TRUSTED_HOSTS"] = [urlparse(public_base_url).netloc]

        if not app.config["ADMIN_ALERT_RECIPIENT"]:
            raise RuntimeError(
                "ADMIN_ALERT_RECIPIENT must be configured before starting in production."
            )

    # --------------------------
    # INITIALIZE EXTENSIONS
    # --------------------------
    db.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    register_maintenance_commands(app)

    using_local_sqlite = app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
    if not is_production and using_local_sqlite:
        with app.app_context():
            db.create_all()

    app.jinja_env.filters['time_ago'] = time_ago
    app.jinja_env.filters['display_time'] = time_ago  # Alias for time_ago

    global password_reset_serializer
    password_reset_serializer = URLSafeTimedSerializer(
        app.secret_key,
        salt="student-password-reset"
    )

    # --------------------------
    # CONTEXT PROCESSORS
    # --------------------------
    @app.context_processor
    def inject_global_context():
        unread_count = 0
        unread_message_count = 0
        admin_unread_count = 0
        current_user_pic = None

        try:
            if "student" in session:
                cache = session.get("nav_counts_cache") or {}
                now = time.time()
                if (
                    cache.get("role") == "student"
                    and cache.get("user_id") == session["student"]
                    and now - cache.get("ts", 0) < 20
                ):
                    unread_count = cache.get("unread_count", 0)
                    unread_message_count = cache.get("unread_message_count", 0)
                else:
                    unread_count = Notification.query.filter_by(
                        user_id=session["student"],
                        is_read=False
                    ).count()

                    unread_message_count = PrivateMessage.query.filter_by(
                        receiver_id=session["student"],
                        is_read=False
                    ).count()
                    session["nav_counts_cache"] = {
                        "role": "student",
                        "user_id": session["student"],
                        "ts": now,
                        "unread_count": unread_count,
                        "unread_message_count": unread_message_count,
                    }

                student = getattr(g, "current_student", None)
                if student and student.profile_pic:
                    current_user_pic = student.profile_pic

            elif "admin" in session:
                cache = session.get("nav_counts_cache") or {}
                now = time.time()
                if cache.get("role") == "admin" and now - cache.get("ts", 0) < 20:
                    admin_unread_count = cache.get("admin_unread_count", 0)
                else:
                    admin_unread_count = AdminNotification.query.filter_by(
                        is_read=False
                    ).count()
                    session["nav_counts_cache"] = {
                        "role": "admin",
                        "ts": now,
                        "admin_unread_count": admin_unread_count,
                    }
        except Exception:
            db.session.rollback()
            app.logger.warning("Global navigation counters are unavailable for this request.", exc_info=True)

        return dict(
            csrf_token=csrf_token,
            unread_count=unread_count,
            unread_message_count=unread_message_count,
            admin_unread_count=admin_unread_count,
            current_user_pic=current_user_pic,
        )

    @app.before_request
    def before_request_handlers():

        g.request_started_at = time.perf_counter()
        g.verify_password_and_upgrade = verify_password_and_upgrade
        g.current_student = None
        lightweight_endpoints = {"static", "service_worker", "manifest", "main.stream"}

        if request.endpoint not in lightweight_endpoints and "student" in session:
            try:
                g.current_student = Student.query.filter_by(
                    student_id=session["student"]
                ).first()
            except Exception:
                db.session.rollback()
                app.logger.warning("Unable to load current student for this request.", exc_info=True)

        if request.endpoint not in lightweight_endpoints | {"main.upload_allowed_students", "main.add_lost_item"}:

            for file_storage in request.files.values():

                if (
                    file_storage
                    and file_storage.filename
                    and not upload_content_is_safe(file_storage)
                ):
                    abort(
                        400,
                        description="The uploaded file does not match a supported file type.",
                    )

    @app.after_request
    def log_slow_requests(response):
        started_at = getattr(g, "request_started_at", None)
        if started_at is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            threshold_ms = app.config.get("SLOW_REQUEST_LOG_MS", 700)
            if elapsed_ms >= threshold_ms and request.endpoint not in {"static", "main.stream"}:
                app.logger.warning(
                    "Slow request: %.0fms %s %s endpoint=%s status=%s",
                    elapsed_ms,
                    request.method,
                    request.path,
                    request.endpoint,
                    response.status_code,
                )
        return response

    # --------------------------
    # REGISTER BLUEPRINTS
    # --------------------------

    @app.route('/manifest.json')
    def manifest():
        return send_from_directory(app.static_folder, 'manifest.json', mimetype='application/manifest+json')

    @app.route('/sw.js')
    def service_worker():
        response = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    try:
        auth_module = importlib.import_module(".auth", __package__)
    except (ImportError, SystemError, TypeError):
        auth_module = importlib.import_module("auth")
    else:
        auth_module = importlib.reload(auth_module)

    if auth_module.__name__ == "auth":
        auth_module = importlib.reload(auth_module)

    auth_bp = auth_module.auth_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)

    app.wsgi_app = passthrough_wsgi_app(app.wsgi_app)

    # Backward-compatible endpoint aliases for templates that still reference
    # legacy, unprefixed route names.
    endpoint_aliases = {
        'home': 'main.home',
        'campus_news': 'main.campus_news',
        'add_news_post': 'main.add_news_post',
        'edit_news_post': 'main.edit_news_post',
        'delete_news_post': 'main.delete_news_post',
        'like_news_post': 'main.like_news_post',
        'add_news_comment': 'main.add_news_comment',
        'delete_news_comment': 'main.delete_news_comment',
        'edit_news_comment': 'main.edit_news_comment',
        'notifications': 'main.notifications',
        'mark_notification_read': 'main.mark_notification_read',
        'mark_all_notifications_read': 'main.mark_all_notifications_read',
        'add_event': 'main.add_event',
        'event_detail': 'main.event_detail',
        'edit_event': 'main.edit_event',
        'edit_event_description': 'main.edit_event_description',
        'delete_event': 'main.delete_event',
        'like_event': 'main.like_event',
        'register_event': 'main.register_event',
        'add_comment': 'main.add_comment',
        'delete_comment': 'main.delete_comment',
        'edit_comment': 'main.edit_comment',
        'lost_found': 'main.lost_found',
        'add_lost_item': 'main.add_lost_item',
        'resolve_item': 'main.resolve_item',
        'delete_lost_item': 'main.delete_lost_item',
        'doubts': 'main.doubts',
        'add_doubt': 'main.add_doubt',
        'reply_doubt': 'main.reply_doubt',
        'delete_doubt': 'main.delete_doubt',
        'delete_doubt_reply': 'main.delete_doubt_reply',
        'polls': 'main.polls',
        'create_poll': 'main.create_poll',
        'vote': 'main.vote',
        'delete_poll': 'main.delete_poll',
        'admin_login': 'main.admin_login',
        'admin_dashboard': 'main.admin_dashboard',
        'admin_profile': 'main.admin_profile',
        'admin_notifications': 'main.admin_notifications',
        'admin_feedback': 'main.admin_feedback',
        'reply_to_feedback': 'main.reply_to_feedback',
        'admin_reports': 'main.admin_reports',
        'reply_to_report': 'main.reply_to_report',
        'update_report_status': 'main.update_report_status',
        'action_report': 'main.action_report',
        'admin_recovery_requests': 'main.admin_recovery_requests',
        'issue_admin_recovery_link': 'main.issue_admin_recovery_link',
        'export_students': 'main.export_students',
        'view_allowed_students': 'main.view_allowed_students',
        'add_allowed_student': 'main.add_allowed_student',
        'upload_allowed_students': 'main.upload_allowed_students',
        'delete_allowed_student': 'main.delete_allowed_student',
        'delete_allowed_students_bulk': 'main.delete_allowed_students_bulk',
        'student_profile': 'main.student_profile',
        'student_dashboard': 'main.student_dashboard',
        'student_settings': 'main.student_settings',
        'followers_list': 'main.followers_list',
        'update_profile_pic': 'main.update_profile_pic',
        'remove_profile_pic': 'main.remove_profile_pic',
        'follow_user': 'main.follow_user',
        'delete_skill': 'main.delete_skill',
        'endorse_skill': 'main.endorse_skill',
        'get_skill_endorsers': 'main.get_skill_endorsers',
        'skill_exchange_hub': 'main.skill_exchange_hub',
        'projects': 'main.projects',
        'add_project': 'main.add_project',
        'view_project': 'main.view_project',
        'like_project': 'main.like_project',
        'add_project_comment': 'main.add_project_comment',
        'delete_project': 'main.delete_project',
        'delete_project_comment': 'main.delete_project_comment',
        'edit_project_comment': 'main.edit_project_comment',
        'submit_suggestion': 'main.submit_suggestion',
        'admin_suggestions': 'main.admin_suggestions',
        'update_suggestion_status': 'main.update_suggestion_status',

        'notice_board': 'main.notice_board',
        'admin_manage_notices': 'main.admin_manage_notices',
        'feedback': 'main.feedback',
        'submit_report': 'main.submit_report',
        'inbox': 'main.inbox',
        'chat': 'main.chat',
        'delete_message': 'main.delete_message',
        'gpa_calculator': 'main.gpa_calculator',
        'planner': 'main.planner',
        'add_task': 'main.add_task',
        'toggle_task': 'main.toggle_task',
        'delete_task': 'main.delete_task',
        'resources': 'main.resources',
        'add_resource': 'main.add_resource',
        'delete_resource': 'main.delete_resource',
        'download_resource_file': 'main.download_resource_file',
        'view_resource': 'main.view_resource',
        'delete_resource_comment': 'main.delete_resource_comment',
        'toggle_save_resource': 'main.toggle_save_resource',
        'saved_resources': 'main.saved_resources',
        'gallery': 'main.gallery',
        'opportunities': 'main.opportunities',
        'add_opportunity': 'main.add_opportunity',
        'delete_opportunity': 'main.delete_opportunity',
        'global_search': 'main.global_search',
        'privacy_policy': 'main.privacy_policy',
        'offline_page': 'main.offline_page',
        'placement': 'main.placement',
        'resume_analyzer': 'main.resume_analyzer',
        'analyze_placement': 'main.analyze_placement',
        'phone_recovery': 'main.phone_recovery',
        'verify_phone_recovery': 'main.verify_phone_recovery',
        'reset_password_by_phone': 'main.reset_password_by_phone',
        'student_login': 'auth.student_login',
        'student_register': 'auth.student_register',
        'request_admin_recovery': 'auth.request_admin_recovery',
        'forgot_password': 'auth.forgot_password',
        'reset_password': 'auth.reset_password',
        'logout': 'auth.logout',
    }

    for alias, target in endpoint_aliases.items():
        if alias in app.view_functions or target not in app.view_functions:
            continue
        target_rule = next((rule for rule in app.url_map.iter_rules(target)), None)
        if target_rule:
            methods = sorted(target_rule.methods - {'HEAD', 'OPTIONS'})
            app.add_url_rule(
                target_rule.rule,
                endpoint=alias,
                view_func=app.view_functions[target],
                methods=methods,
            )

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    import_default_allowed_students(app)
    seed_development_accounts(app)
    log_database_login_summary(app)

    return app


# --------------------------
# APP START
# --------------------------

env_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".env",
)

load_dotenv(env_path, override=False)

app = create_app()

if __name__ == "__main__":

    debug_mode = os.getenv(
        "FLASK_DEBUG",
        "False",
    ).lower() == "true"

    if is_production and debug_mode:
        raise RuntimeError(
            "FLASK_DEBUG must be disabled in production."
        )

    print("STARTING SERVER ON PORT 5001")

    app.run(
        host="0.0.0.0",
        port=5001,
        debug=debug_mode,
        use_reloader=False,
    )
