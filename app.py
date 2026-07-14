from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, abort, send_from_directory
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, func
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
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from datetime import datetime, timedelta
from markupsafe import escape
import calendar
import hmac
import secrets
from functools import wraps
from urllib.parse import urlparse, urljoin
from PyPDF2 import PdfReader
try:
    from google import genai
except ImportError:
    # AI is optional; administrative tools and account recovery must still run
    # when the Gemini SDK is not installed.
    genai = None
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
# Hosting-provider secrets must take precedence over any local .env file.
load_dotenv(env_path, override=False)

app = Flask(__name__)

is_production = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower() == "production"
trusted_proxy_count = int(os.getenv("TRUST_PROXY_COUNT", "0"))
if trusted_proxy_count:
    # Only trust forwarding headers from the explicitly configured number of proxies.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_proxy_count, x_proto=trusted_proxy_count, x_host=trusted_proxy_count)
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    if is_production:
        raise RuntimeError("SECRET_KEY must be configured before starting in production.")
    # A random development key avoids accidentally deploying a known default key.
    secret_key = secrets.token_urlsafe(48)
    app.logger.warning("SECRET_KEY is not set; using a temporary development-only key.")
app.secret_key = secret_key
app.config.update(
    MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
    MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "true").lower() in {"1", "true", "yes"},
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_USERNAME"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=is_production,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
public_base_url = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
if public_base_url:
    parsed_public_url = urlparse(public_base_url)
    if parsed_public_url.scheme not in {"http", "https"} or not parsed_public_url.netloc:
        raise RuntimeError("PUBLIC_BASE_URL must be a complete http(s) URL.")
elif is_production:
    raise RuntimeError("PUBLIC_BASE_URL must be configured before starting in production.")

if is_production:
    app.config["PREFERRED_URL_SCHEME"] = "https"
    # Flask enforces this when running on Flask 3.1+ (pinned in requirements).
    app.config["TRUSTED_HOSTS"] = [urlparse(public_base_url).netloc]

mail = Mail(app)
ADMIN_ALERT_RECIPIENT = os.getenv('ADMIN_ALERT_RECIPIENT')
if is_production and not ADMIN_ALERT_RECIPIENT:
    raise RuntimeError("ADMIN_ALERT_RECIPIENT must be configured before starting in production.")
FAST2SMS_API_KEY = os.getenv('FAST2SMS_API_KEY')
FAST2SMS_OTP_ID = os.getenv('FAST2SMS_OTP_ID')

# GEMINI API CONFIGURATION
# Support the existing deployment variable name while preferring the explicit one.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
gemini_client = None
if genai and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"🔴 WARNING: Gemini API Key could not be configured. AI features will be disabled. Error: {e}")
        GEMINI_API_KEY = None # Disable AI if key is invalid
elif not genai and GEMINI_API_KEY:
    print("🟡 WARNING: google-genai is not installed. AI features will be disabled.")
    GEMINI_API_KEY = None

password_reset_serializer = URLSafeTimedSerializer(app.secret_key, salt="student-password-reset")
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
    row = AuthRateLimit.query.filter_by(key=f"login:{key}").first()
    if row:
        db.session.delete(row)
        db.session.commit()


def rate_limit_reached(key, limit, window):
    row = AuthRateLimit.query.filter_by(key=key).first()
    return bool(row and row.window_started_at > datetime.now() - window and row.attempt_count >= limit)


def record_rate_limit_attempt(key, window):
    now = datetime.now()
    row = AuthRateLimit.query.filter_by(key=key).first()
    if not row:
        row = AuthRateLimit(key=key, window_started_at=now, attempt_count=1)
        db.session.add(row)
    elif row.window_started_at <= now - window:
        row.window_started_at, row.attempt_count = now, 1
    else:
        row.attempt_count += 1
    db.session.commit()


def csrf_token():
    """Return a session-bound token for destructive browser actions."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': csrf_token()}


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
    return wrapped


@app.before_request
def protect_authenticated_mutations():
    """Apply CSRF protection consistently to every signed-in POST request."""
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and ('student' in session or 'admin' in session):
        submitted_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not submitted_token or not hmac.compare_digest(submitted_token, csrf_token()):
            abort(400, description='Invalid or missing security token.')

# UPLOAD CONFIGURATION
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'media')
# Resources are served through an authenticated route, never directly from /static.
app.config['RESOURCE_FOLDER'] = os.path.join(app.root_path, 'private_uploads', 'resources')
app.config['LEGACY_RESOURCE_FOLDER'] = os.path.join(app.root_path, 'static', 'media', 'resources')
app.config['CSS_FOLDER'] = os.path.join(app.root_path, 'static', 'css')

# Ensure upload directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESOURCE_FOLDER'], exist_ok=True)
os.makedirs(app.config['CSS_FOLDER'], exist_ok=True)

app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'mp4', 'mov', 'avi', 'webm', 'pdf', 'docx', 'doc', 'pptx', 'ppt', 'txt'}
app.config['RESOURCE_EXTENSIONS'] = {'pdf', 'docx', 'doc', 'pptx', 'ppt', 'txt'}
app.config['RESUME_EXTENSIONS'] = {'pdf', 'docx', 'txt'}
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # Increased to 64MB to support modern high-res media

IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic'}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def allowed_media_file(filename):
    """Media fields must not accept documents merely because they are allowed elsewhere."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def upload_content_is_safe(file_storage):
    """Reject files whose bytes do not match their claimed safe type.

    This is intentionally a lightweight first line of defense, not a substitute
    for server-side malware scanning in production.
    """
    filename = secure_filename(file_storage.filename or '')
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in app.config['ALLOWED_EXTENSIONS']:
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


@app.before_request
def reject_disguised_uploads():
    """Validate all ordinary uploads before any handler writes them to disk."""
    if request.endpoint == 'upload_allowed_students':
        return
    for file_storage in request.files.values():
        if file_storage and file_storage.filename and not upload_content_is_safe(file_storage):
            abort(400, description='The uploaded file does not match a supported file type.')


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


def public_url_for(endpoint, **values):
    """Build security-sensitive public links from the configured canonical origin."""
    path = url_for(endpoint, **values)
    if public_base_url:
        return urljoin(f"{public_base_url}/", path.lstrip('/'))
    return url_for(endpoint, _external=True, **values)


def remove_uploaded_media(filename):
    """Delete a uniquely-named public upload when its database record is removed."""
    if not filename:
        return
    path = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(filename))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        app.logger.warning('Could not remove uploaded media: %s', filename)

# DATABASE CONNECTION
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("🔴 FATAL ERROR: DATABASE_URL not found in .env file.")
    import sys
    sys.exit(1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)


def verify_password_and_upgrade(account, submitted_password):
    """Verify current hashes and transparently upgrade passwords from legacy data."""
    stored_password = account.password or ""
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
    return False

# AVAILABLE DEPARTMENTS
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

# AI RECOMMENDATION KEYWORDS
INTERESTS = {
    'Computer Science & Systems Engineering': ['hackathon', 'coding', 'ai', 'data', 'cyber', 'tech', 'web', 'app', 'software', 'programming'],
    'Electronics & Communication Engineering': ['circuit', 'electronics', 'signal', 'iot', 'embedded', 'communication', 'vlsi'],
    'Electrical Engineering': ['power', 'electrical', 'energy', 'solar', 'circuit', 'grid'],
    'Mechanical Engineering': ['robotics', 'cad', 'design', 'auto', 'mechanics', 'thermal', 'manufacturing'],
    'Civil Engineering': ['structure', 'concrete', 'survey', 'construction', 'design', 'infrastructure'],
    'Information Technology & Computer Applications': ['computer', 'application', 'software', 'web', 'information'],
    'Chemical Engineering': ['chemistry', 'reaction', 'process', 'material', 'thermodynamics', 'fluid'],
    'Metallurgical Engineering': ['metal', 'materials', 'alloy', 'smelting', 'casting', 'steel'],
    'Instrument Technology': ['sensors', 'instrumentation', 'control', 'measurement', 'calibration', 'automation'],
    'Marine Engineering': ['ship', 'ocean', 'marine', 'naval', 'vessel', 'propulsion', 'maritime']
}

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

# TIME FILTER
@app.template_filter('time_ago')
def time_ago(date):
    if not date:
        return ""
    
    now = datetime.now()
    diff = now - date
    seconds = diff.total_seconds()
    
    clock_time = date.strftime('%I:%M %p').lstrip('0')
    if date.date() == now.date():
        return f"Today at {clock_time}"
    if date.date() == (now - timedelta(days=1)).date():
        return f"Yesterday at {clock_time}"
    return f"{date.strftime('%d %b %Y')} at {clock_time}"

@app.template_filter('display_time')
def display_time(date):
    """Show every saved action timestamp with a readable 12-hour clock."""
    if not date:
        return ""
    return f"{date.strftime('%d %b %Y')} at {date.strftime('%I:%M %p').lstrip('0')}"

# ERROR HANDLERS
@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    flash("File is too large! Maximum size allowed is 64MB.")
    return redirect(safe_redirect_target(url_for('home')))

@app.after_request
def add_no_cache_headers(response):
    if request.endpoint in {'admin_login', 'student_login'}:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' data: https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
    )
    if is_production:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response

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
    profile_pic = db.Column(db.String(200))

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


class RecoveryRequest(db.Model):
    """A password-recovery request that requires an administrator identity check."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), nullable=False, index=True)
    contact_note = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), nullable=False, default='Pending', index=True)
    reviewed_by = db.Column(db.String(20), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

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


# =========================
# NOTIFICATION LOGIC
# =========================

@app.context_processor
def inject_notifications():
    unread_count = 0
    unread_message_count = 0
    admin_unread_count = 0
    current_user_pic = None
    if 'student' in session:
        unread_count = Notification.query.filter_by(user_id=session['student'], is_read=False).count()
        unread_message_count = PrivateMessage.query.filter_by(receiver_id=session['student'], is_read=False).count()
        student = Student.query.filter_by(student_id=session['student']).first()
        if student and student.profile_pic:
            current_user_pic = student.profile_pic
    elif 'admin' in session:
        admin_unread_count = AdminNotification.query.filter_by(is_read=False).count()

    return dict(unread_count=unread_count, unread_message_count=unread_message_count,
                admin_unread_count=admin_unread_count, current_user_pic=current_user_pic)


def create_admin_notification(category, message, endpoint):
    """Queue an administrator alert within the same database transaction as its event."""
    db.session.add(AdminNotification(
        category=category,
        message=message,
        link=url_for(endpoint),
    ))


def send_admin_alert(subject, title, details):
    """Email the admin without letting an email outage lose the in-app alert."""
    if not ADMIN_ALERT_RECIPIENT:
        app.logger.warning('Admin alert email is not configured; keeping the in-app alert only.')
        return
    try:
        mail.send(Message(
            subject=subject,
            recipients=[ADMIN_ALERT_RECIPIENT],
            html=render_template('admin_alert_email.html', title=title, details=details),
        ))
    except Exception:
        app.logger.exception('Unable to send admin alert email')


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
            app.logger.exception('Unable to send student admin-reply email')


def normalize_indian_mobile(value):
    """Return a 10-digit Indian mobile number, or None for invalid input."""
    digits = re.sub(r'\D', '', value or '')
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    return digits if len(digits) == 10 and digits[0] in '6789' else None


def fast2sms_otp_request(endpoint, payload):
    """Call Fast2SMS Smart OTP without exposing provider errors to users."""
    if not FAST2SMS_API_KEY or not FAST2SMS_OTP_ID:
        raise RuntimeError('Phone recovery is not configured. Set FAST2SMS_API_KEY and FAST2SMS_OTP_ID.')
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(
        f'https://www.fast2sms.com/dev/otp/{endpoint}', data=data, method='POST',
        headers={'Authorization': FAST2SMS_API_KEY, 'Content-Type': 'application/json'},
    )
    try:
        with urlrequest.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        app.logger.warning('Fast2SMS %s request failed: %s', endpoint, error)
        return {'return': False}

def check_upcoming_events(user_id):
    """Checks for events happening tomorrow and creates reminders."""
    today = datetime.now().date()
    tomorrow_str = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Directly query events matching tomorrow's date string
    upcoming_events = Event.query.filter_by(date=tomorrow_str).all()
    
    for event in upcoming_events:
        # Check if reminder already exists
        exists = Notification.query.filter_by(user_id=user_id, event_id=event.id, type='reminder').first()
        if not exists:
            msg = f"Reminder: '{event.title}' is happening tomorrow!"
            db.session.add(Notification(user_id=user_id, message=msg, type='reminder', event_id=event.id))
    db.session.commit()

@app.route('/manifest.json')
def serve_manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def serve_sw():
    return app.send_static_file('sw.js')

# =========================
# HOME PAGE
# =========================

@app.route('/')
def home():
    user_id = session.get('student') or session.get('admin')
    if not user_id:
        # If not logged in, show the welcome landing page
        return render_template("welcome.html")

    # CRITICAL FIX: If admin clicks "Home", redirect to their dashboard, not the student feed.
    if 'admin' in session:
        return redirect(url_for('admin_dashboard'))


    student = None
    current_user_name = None
    user_department = None
    if 'student' in session:
        student = Student.query.filter_by(student_id=session['student']).first()
        if not student:
            session.clear()
            return render_template("welcome.html")
        current_user_name = student.name
        # Check for automatic reminders for the logged-in student
        user_department = student.department #Store User Department
        
        check_upcoming_events(session['student'])
    elif 'admin' in session:
        current_user_name = "Admin"

    page = request.args.get('page', 1, type=int)
    per_page = 9  # Show 9 events per page

    # Search Logic
    search_query = request.args.get('q')
    if search_query:
        events_query = Event.query.filter(
            or_(Event.title.ilike(f'%{search_query}%'),
                Event.department.ilike(f'%{search_query}%'))
        )
    else:
        events_query = Event.query
    
    #Department Filter
    selected_depts = request.args.getlist('dept_filter')
    if selected_depts:
        events_query = events_query.filter(Event.department.in_(selected_depts))

    pagination = events_query.order_by(Event.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    events = pagination.items

    # Recommendation Engine
    if student and student.department:
        # Calculate a relevance score for each event based on user's department and interests
        def get_recommendation_score(event):
            score = 0
            # 1. Direct Department Match (High Priority)
            if event.department == student.department:
                score += 10
            # 2. General Events (Medium Priority)
            elif event.department == 'General':
                score += 5
            
            # 3. Content-Based Filtering (Keywords)
            keywords = INTERESTS.get(student.department, [])
            content = (event.title + " " + event.description).lower()
            for kw in keywords:
                if kw in content:
                    score += 2
            return score

        # Attach score to each event
        for event in events:
            event.recommendation_score = get_recommendation_score(event)
        
        # Sort events by recommendation score, then by ID as a tie-breaker
        events.sort(key=lambda x: (x.recommendation_score, x.id), reverse=True)

    # Process events for display
    for event in events:
        event.like_count = EventLike.query.filter_by(event_id=event.id).count()
        
        # Fetch comments with commenter's profile pic
        comments_data = db.session.query(Comment, Student.profile_pic)\
            .outerjoin(Student, Comment.user_id == Student.student_id)\
            .filter(Comment.event_id == event.id)\
            .order_by(Comment.timestamp.asc()).all()
        
        event.comments = []
        for comment, profile_pic in comments_data:
            comment.user_profile_pic = profile_pic
            event.comments.append(comment)

        event.user_liked = EventLike.query.filter_by(user_id=user_id, event_id=event.id).first() is not None
        event.is_registered = EventRegistration.query.filter_by(user_id=user_id, event_id=event.id).first() is not None

        # Flag for UI Badge
        event.is_recommended = False
        if student and student.department:
            if hasattr(event, 'recommendation_score') and event.recommendation_score >= 5:
                event.is_recommended = True

    return render_template(
        "index.html", 
        events=events, 
        pagination=pagination,
        current_user_name=current_user_name, 
        user_department=user_department, 
        departments=DEPARTMENTS, 
        selected_depts=selected_depts
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
        if not GEMINI_API_KEY:
            # Fallback to simple keyword matching if API key is missing
            jd_words = {
                word for word in re.findall(r"\b[a-zA-Z][a-zA-Z+#.]{2,}\b", job_description.lower())
                if word not in {"and", "the", "for", "with", "you", "are", "this", "that", "will", "from", "our", "your"}
            }
            resume_words = set(words)
            matched = sorted(jd_words & resume_words)
            missing = sorted(jd_words - resume_words)[:12]
            match_score = round((len(matched) / max(len(jd_words), 1)) * 100)
            jd_match = {"score": match_score, "matched": matched[:16], "missing": missing, "ai_analysis": "Disabled"}
            if match_score >= 35:
                score += 10
                strengths.append("Job description alignment")
            else:
                improvements.append("Customize the resume using important keywords from the target job description.")
        else:
            # Use Gemini API for advanced analysis
            try:
                prompt = f"Analyze this resume:\n\n{text}\n\nAgainst this job description:\n\n{job_description}\n\nProvide a match score (0-100), a list of matched skills, and a list of missing skills. Format the output as a simple dictionary string: {{'score': <score>, 'matched': ['skill1', 'skill2'], 'missing': ['skill3', 'skill4']}}"
                response = gemini_client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
                # Basic parsing of the string response to a dict
                response_dict_str = response.text.strip().replace("'", '"')
                jd_match = json.loads(response_dict_str)
                jd_match["ai_analysis"] = "Enabled"
            except Exception as e:
                app.logger.error(f"Gemini API call failed: {e}")
                jd_match = {"score": 0, "matched": [], "missing": [], "ai_analysis": f"Error: {str(e)}"}

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

@app.route('/resume_analyzer', methods=['GET', 'POST'])
def resume_analyzer():
    if request.method == 'POST':
        if 'student' not in session and 'admin' not in session:
            flash('Please sign in before analyzing a resume.', 'warning')
            return redirect(url_for('student_login'))

        resume_file = request.files.get('resume')
        job_description = request.form.get('job_description', '')

        if not resume_file or resume_file.filename == '':
            flash('Please upload a resume file.', 'warning')
            return render_template('resume_analyzer.html'), 400

        ext = resume_file.filename.rsplit('.', 1)[1].lower() if '.' in resume_file.filename else ""
        if ext not in app.config['RESUME_EXTENSIONS']:
            flash(f"Please upload only {', '.join(sorted(app.config['RESUME_EXTENSIONS']))} files.", 'warning')
            return render_template('resume_analyzer.html'), 400

        try:
            text = extract_resume_text(resume_file)
            result = analyze_resume_text(text, job_description)
            return render_template('resume_analyzer.html', result=result, resume_filename=secure_filename(resume_file.filename))
        except ValueError as e:
            app.logger.info('Resume upload could not be read: %s', e)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': str(e)}), 422
            flash(str(e), 'warning')
            return render_template('resume_analyzer.html'), 422
        except Exception as e:
            # Use traceback to get detailed exception info for logging
            import traceback
            app.logger.error("--- RESUME ANALYSIS FAILED ---")
            app.logger.error(traceback.format_exc())
            error_message = "The resume could not be analyzed due to a server error. Please try again later."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                # CRITICAL FIX: Return a JSON error for AJAX, not an HTML page
                return jsonify({'error': error_message}), 500
            flash(error_message, 'danger')
            return render_template('resume_analyzer.html'), 500

    # Handle GET requests (just showing the page)
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    return render_template("resume_analyzer.html")

@app.route('/placement', methods=['GET']) # Only GET for rendering the page
def placement():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    return render_template("placement.html")

@app.route('/analyze_placement', methods=['POST']) # New route for AJAX POST
def analyze_placement():
    if 'student' not in session and 'admin' not in session:
        return jsonify({'success': False, 'error': 'Authentication required'}), 401

    resume_file = request.files.get('resume')
    job_description = request.form.get('job_link', '')

    if not resume_file or resume_file.filename == '':
        return jsonify({'success': False, 'error': 'Please upload a resume file.'})

    ext = resume_file.filename.rsplit('.', 1)[1].lower() if '.' in resume_file.filename else ""
    if ext not in app.config['RESUME_EXTENSIONS']:
        return jsonify({'success': False, 'error': f"Please upload only {', '.join(app.config['RESUME_EXTENSIONS'])} files."})

    try:
        text = extract_resume_text(resume_file)
        result = analyze_resume_text(text, job_description)
        return jsonify({'success': True, 'analysis': result})
    except Exception as e:
        import traceback
        app.logger.error("--- PLACEMENT ANALYSIS (AJAX) FAILED ---")
        app.logger.error(traceback.format_exc())
        # Return a specific error to the client for better debugging.
        return jsonify({'success': False, 'error': 'Resume analysis failed due to a server error. Please try again later.'}), 500


# =========================
# CAMPUS NEWS FEED
# =========================

@app.route('/campus_news')
def campus_news():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

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
        return render_template('_news_posts.html', posts=posts)

    return render_template("campus_news.html", posts=posts, pagination=posts_pagination, feed_type=feed_type)

@app.route('/add_news_post', methods=['POST'])
def add_news_post():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

    content = request.form.get('content')
    if not content or len(content.strip()) == 0:
        flash("Post content cannot be empty.")
        return redirect(url_for('campus_news'))

    # Handle Image Upload
    image = request.files.get('image')
    image_filename = None
    if image and image.filename != '':
        if allowed_media_file(image.filename):
            image_filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        else:
            flash("Invalid file type. Only images and videos are allowed.")
            return redirect(url_for('campus_news')) # Ensure redirect on error

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
    return redirect(url_for('campus_news'))

@app.route('/edit_news_post/<int:post_id>', methods=['POST'])
def edit_news_post(post_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

    post = NewsPost.query.get_or_404(post_id)
    current_user = session.get('student') or session.get('admin')

    if post.user_id == current_user or 'admin' in session:
        new_content = request.form.get('content')
        if new_content and new_content.strip():
            post.content = new_content.strip()
            db.session.commit()
            
    return redirect(safe_redirect_target(url_for('campus_news')))

@app.route('/delete_news_post/<int:post_id>', methods=['POST'])
@require_csrf
def delete_news_post(post_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

    post = NewsPost.query.get_or_404(post_id)
    current_user = session.get('student') or session.get('admin')

    if post.user_id == current_user or 'admin' in session:
        remove_uploaded_media(post.image_file)
        db.session.delete(post)
        db.session.commit()
        flash("Post deleted.")
    else:
        flash("You are not authorized to delete this post.")
    
    return redirect(url_for('campus_news'))

@app.route('/like_news/<int:post_id>', methods=['POST'])
@require_csrf
def like_news_post(post_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

    user_id = session.get('student') or session.get('admin')
    
    existing_like = NewsLike.query.filter_by(user_id=user_id, post_id=post_id).first()

    if existing_like:
        db.session.delete(existing_like)
    else:
        new_like = NewsLike(user_id=user_id, post_id=post_id)
        db.session.add(new_like)
    
    db.session.commit()
    return jsonify({'success': True, 'likes': NewsLike.query.filter_by(post_id=post_id).count(), 'liked': not existing_like})

@app.route('/comment_news/<int:post_id>', methods=['POST'])
def add_news_comment(post_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
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

@app.route('/delete_news_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def delete_news_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    comment = NewsComment.query.get_or_404(comment_id)
    current_user = session.get('student') or session.get('admin')
    
    if comment.user_id == current_user or 'admin' in session:
        db.session.delete(comment)
        db.session.commit()
        
    return redirect(url_for('campus_news'))

@app.route('/edit_news_comment/<int:comment_id>', methods=['POST'])
def edit_news_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    comment = NewsComment.query.get_or_404(comment_id)
    current_user = session.get('student') or session.get('admin')
    
    if comment.user_id == current_user or 'admin' in session:
        new_content = request.form.get('content')
        if new_content and new_content.strip():
            comment.content = new_content.strip()
            db.session.commit()
            
    return redirect(safe_redirect_target(url_for('campus_news')))

@app.route('/notifications')
def notifications():
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    user_id = session['student']
    # Fetch all notifications, newest first
    notifs = Notification.query.filter_by(user_id=user_id).order_by(Notification.timestamp.desc()).all()
    
    return render_template("notifications.html", notifications=notifs)

@app.route('/notifications/mark_read/<int:id>', methods=['POST'])
@require_csrf
def mark_notification_read(id):
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    notif = Notification.query.get_or_404(id)
    if notif.user_id == session['student']:
        notif.is_read = True
        db.session.commit()
    return redirect(url_for('notifications'))

@app.route('/notifications/mark_all_read', methods=['POST'])
@require_csrf
def mark_all_notifications_read():
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    user_id = session['student']
    Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()
    return redirect(url_for('notifications'))

@app.route('/like/<int:event_id>', methods=['POST'])
@require_csrf
def like_event(event_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

    user_id = session.get('student') or session.get('admin')
    
    existing_like = EventLike.query.filter_by(user_id=user_id, event_id=event_id).first()

    if existing_like:
        db.session.delete(existing_like)
    else:
        new_like = EventLike(user_id=user_id, event_id=event_id)
        db.session.add(new_like)
    
    db.session.commit()
    return jsonify({'success': True, 'likes': EventLike.query.filter_by(event_id=event_id).count(), 'liked': not existing_like})

@app.route('/register_event/<int:event_id>', methods=['POST'])
@require_csrf
def register_event(event_id):
    if 'student' not in session:
        return redirect(url_for('student_login'))

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
    return redirect(request.referrer or url_for('home'))

@app.route('/comment/<int:event_id>', methods=['POST'])
def add_comment(event_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
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

@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def delete_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    comment = Comment.query.get_or_404(comment_id)
    current_user = session.get('student') or session.get('admin')
    
    # Allow deletion if user owns the comment OR is an admin
    if comment.user_id == current_user or 'admin' in session:
        db.session.delete(comment)
        db.session.commit()
        
    return redirect(request.referrer or url_for('home'))

@app.route('/edit_comment/<int:comment_id>', methods=['POST'])
def edit_comment(comment_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    comment = Comment.query.get_or_404(comment_id)
    current_user = session.get('student') or session.get('admin')
    
    if comment.user_id == current_user or 'admin' in session:
        new_content = request.form.get('content')
        if new_content and new_content.strip():
            comment.content = new_content.strip()
            db.session.commit()
            
    return redirect(request.referrer or url_for('home'))

# =========================
# LOST & FOUND
# =========================

@app.route('/lost_found')
def lost_found():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    # Show active items first, resolved last
    items = LostItem.query.order_by(LostItem.is_resolved.asc(), LostItem.timestamp.desc()).all()
    return render_template("lost_found.html", items=items)

@app.route('/add_lost_item', methods=['POST'])
def add_lost_item():
    if 'student' not in session:
        return redirect(url_for('student_login'))

    type = request.form.get('type') # Lost or Found
    item_name = request.form.get('item_name')
    description = request.form.get('description')
    location = request.form.get('location')
    contact = request.form.get('contact')

    image = request.files.get('image')
    image_filename = None
    if image and image.filename != '':
        if allowed_media_file(image.filename):
            image_filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        else:
            flash("Invalid file type.")
            return redirect(url_for('lost_found')) # Ensure redirect on error

    new_item = LostItem(
        type=type,
        item_name=item_name,
        description=description,
        location=location,
        contact=contact,
        image_file=image_filename,
        user_id=session['student']
    )
    db.session.add(new_item)
    db.session.commit()
    flash("Item reported successfully.")
    return redirect(url_for('lost_found'))

@app.route('/resolve_item/<int:item_id>', methods=['POST'])
@require_csrf
def resolve_item(item_id):
    item = LostItem.query.get_or_404(item_id)
    if 'admin' in session or ('student' in session and session['student'] == item.user_id):
        item.is_resolved = True
        db.session.commit()
        flash("Item marked as resolved/returned.")
    return redirect(url_for('lost_found'))

@app.route('/delete_lost_item/<int:item_id>', methods=['POST'])
@require_csrf
def delete_lost_item(item_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    item = LostItem.query.get_or_404(item_id)
    current_user = session.get('student') or session.get('admin')
    
    if item.user_id == current_user or 'admin' in session:
        if item.image_file:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], item.image_file)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        db.session.delete(item)
        db.session.commit()
        flash("Lost/Found item deleted successfully.")
        
    return redirect(url_for('lost_found'))

# =========================
# ANONYMOUS DOUBTS
# =========================

@app.route('/doubts')
def doubts():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    doubts_list = AnonymousDoubt.query.order_by(AnonymousDoubt.timestamp.desc()).all()
    
    # Standardize name display for anonymity (Works for both Admin and Student)
    for doubt in doubts_list:
        if 'admin' in session:
            author = Student.query.filter_by(student_id=doubt.user_id).first()
            doubt.display_name = author.name if author else "Unknown Student"
        else:
            doubt.display_name = "Anonymous Student"

        for reply in doubt.replies:
            if reply.user_id == session.get('admin'):
                reply.display_name = "Admin"
            elif 'admin' in session:
                author = Student.query.filter_by(student_id=reply.user_id).first()
                reply.display_name = author.name if author else "Unknown Peer"
            else:
                reply.display_name = "Anonymous Peer"

    return render_template("doubts.html", doubts=doubts_list)

@app.route('/add_doubt', methods=['POST'])
def add_doubt():
    if 'student' not in session:
        return redirect(url_for('student_login'))
        
    content = request.form.get('content')
    file = request.files.get('file')
    file_filename = None
    
    if file and file.filename != '':
        if allowed_file(file.filename):
            file_filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], file_filename))
        else:
            flash("Invalid file type attached.") # CRITICAL FIX: Ensure redirect on invalid file type.
            return redirect(url_for('doubts')) # Ensure redirect on error
            
    if content and content.strip():
        new_doubt = AnonymousDoubt(content=content.strip(), user_id=session['student'], file_path=file_filename)
        db.session.add(new_doubt)
        db.session.commit()
        flash("Your anonymous doubt has been posted.")
    return redirect(url_for('doubts'))

@app.route('/reply_doubt/<int:doubt_id>', methods=['POST'])
def reply_doubt(doubt_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
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
    return redirect(url_for('doubts'))

@app.route('/delete_doubt/<int:doubt_id>', methods=['POST'])
@require_csrf
def delete_doubt(doubt_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    doubt = AnonymousDoubt.query.get_or_404(doubt_id)
    # Admin or the student who posted it can delete it
    if 'admin' in session or doubt.user_id == session.get('student'):
        if doubt.file_path:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], doubt.file_path)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        db.session.delete(doubt)
        db.session.commit()
        flash("Doubt deleted.")
    return redirect(url_for('doubts'))

@app.route('/delete_doubt_reply/<int:reply_id>', methods=['POST'])
@require_csrf
def delete_doubt_reply(reply_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    reply = DoubtReply.query.get_or_404(reply_id)
    if 'admin' in session or reply.user_id == session.get('student'):
        db.session.delete(reply)
        db.session.commit()
        flash("Reply deleted.")
    return redirect(url_for('doubts'))

# =========================
# CAMPUS POLLS
# =========================

@app.route('/polls')
def polls():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    user_id = session.get('student') or session.get('admin')
    polls_list = Poll.query.order_by(Poll.timestamp.desc()).all()
    
    # Process polls to calculate percentages
    for poll in polls_list:
        # Fetch creator name
        admin_creator = Admin.query.filter_by(admin_id=poll.created_by).first()
        if admin_creator:
            poll.creator_name = "Administrator"
        else:
            student_creator = Student.query.filter_by(student_id=poll.created_by).first()
            poll.creator_name = student_creator.name if student_creator else "Unknown"

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

@app.route('/create_poll', methods=['GET', 'POST'])
def create_poll():
    # Only admins or logged-in students can create
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

    if request.method == 'POST':
        question = request.form.get('question')
        options_raw = request.form.getlist('options')
        
        # Filter empty options
        options = [opt.strip() for opt in options_raw if opt.strip()]
        
        if question and len(options) >= 2:
            user_id = session.get('student') or session.get('admin')
            
            new_poll = Poll(question=question, created_by=user_id)
            db.session.add(new_poll)
            db.session.commit()
            
            for opt_text in options:
                db.session.add(PollOption(text=opt_text, poll_id=new_poll.id))
            db.session.commit()
            
            flash("Poll created successfully!")
            return redirect(url_for('polls'))
        else:
            flash("Poll must have a question and at least 2 options.")
            
    return render_template("create_poll.html")

@app.route('/vote/<int:poll_id>/<int:option_id>', methods=['POST'])
@require_csrf
def vote(poll_id, option_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    user_id = session.get('student') or session.get('admin')

    # Do not allow a URL to associate an option from one poll with another.
    if not PollOption.query.filter_by(id=option_id, poll_id=poll_id).first():
        abort(404)

    # Check if already voted
    if PollVote.query.filter_by(poll_id=poll_id, user_id=user_id).first():
        flash("You have already voted on this poll.")
        return redirect(url_for('polls'))
        
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
    
    return redirect(url_for('polls'))

@app.route('/delete_poll/<int:poll_id>', methods=['POST'])
@require_csrf
def delete_poll(poll_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    poll = Poll.query.get_or_404(poll_id)
    current_user = session.get('student') or session.get('admin')
    
    if poll.created_by == current_user or 'admin' in session:
        db.session.delete(poll)
        db.session.commit()
        flash("Poll deleted successfully.")
    else:
        flash("You are not authorized to delete this poll.")
        
    return redirect(url_for('polls'))

# =========================
# ADMIN LOGIN
# =========================

@app.route('/admin')
def admin_base():
    if 'admin' in session:
        return redirect(url_for('admin_dashboard'))
    if 'student' in session:
        return redirect(url_for('home'))
    return redirect(url_for('admin_login'))

@app.route('/admin/login', methods=['GET','POST'])
@require_csrf
def admin_login():
    if 'admin' in session:
        return redirect(url_for('admin_dashboard'))
    if 'student' in session:
        return redirect(url_for('home'))

    if request.method == "POST":
        admin_id = request.form.get('admin_id', '').strip()
        password = request.form.get('password', '')
        rate_key = login_rate_limit_key(f'admin:{admin_id}')

        if login_is_rate_limited(rate_key):
            flash('Too many sign-in attempts. Please wait 15 minutes and try again.')
            return render_template("admin_login.html"), 429

        admin = Admin.query.filter_by(admin_id=admin_id).first()

        if admin and password and verify_password_and_upgrade(admin, password):
            clear_login_rate_limit(rate_key)
            session.clear()
            session['admin'] = admin_id
            return redirect(url_for('admin_dashboard'))
        else:
            record_failed_login(rate_key)
            flash("Invalid Admin Login")

    return render_template("admin_login.html")


# =========================
# ADMIN PROFILE
# =========================

@app.route('/admin/profile')
def admin_profile():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    admin = Admin.query.filter_by(admin_id=session['admin']).first()
    if not admin:
        session.clear()
        return redirect(url_for('admin_login'))

    events = Event.query.filter_by(is_admin=True).order_by(Event.id.desc()).all()

    return render_template("admin_profile.html", admin=admin, events=events)


# =========================
# ADMIN DASHBOARD
# =========================

@app.route('/admin/dashboard')
def admin_dashboard():

    if 'admin' not in session:
        return redirect(url_for('admin_login'))

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
                           dept_data=dept_data, top_events=top_events, students=students,
                           student_q=student_q)


@app.route('/admin/notifications')
def admin_notifications():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    notifications = AdminNotification.query.order_by(AdminNotification.timestamp.desc()).all()
    AdminNotification.query.filter_by(is_read=False).update({'is_read': True}, synchronize_session=False)
    db.session.commit()
    return render_template('admin_notifications.html', notifications=notifications)


@app.route('/admin/recovery-requests')
def admin_recovery_requests():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    recovery_requests = RecoveryRequest.query.order_by(
        (RecoveryRequest.status == 'Pending').desc(), RecoveryRequest.created_at.desc()
    ).all()
    return render_template('admin_recovery_requests.html', recovery_requests=recovery_requests)


@app.route('/admin/recovery-requests/<int:request_id>/issue-link', methods=['POST'])
@require_csrf
def issue_admin_recovery_link(request_id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    recovery_request = RecoveryRequest.query.get_or_404(request_id)
    student = Student.query.filter_by(student_id=recovery_request.student_id).first()
    if not student or not student.email:
        flash('No registered email is available for this student. Verify identity and update the account email before issuing a reset link.', 'warning')
        return redirect(url_for('admin_recovery_requests'))

    token = password_reset_serializer.dumps({
        'student_id': student.student_id,
        'password_hash': student.password,
    })
    reset_url = public_url_for('reset_password', token=token)
    recovery_request.status = 'Link issued'
    recovery_request.reviewed_by = session['admin']
    recovery_request.reviewed_at = datetime.now()
    db.session.commit()

    emailed = False
    try:
        mail.send(Message(
            subject='AU Daily password reset',
            recipients=[student.email],
            html=render_template('reset_password_email.html', reset_url=reset_url, name=student.name),
        ))
        emailed = True
    except Exception:
        app.logger.exception('Unable to send administrator-issued password reset email')

    return render_template('admin_recovery_link.html', recovery_request=recovery_request,
                           student=student, reset_url=reset_url, emailed=emailed)


@app.route('/admin/feedback')
def admin_feedback():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
        
    # Fetch all feedback and link it to the student who submitted it
    feedbacks = db.session.query(Feedback, Student.name, Student.department)\
        .outerjoin(Student, Feedback.user_id == Student.student_id)\
        .order_by(Feedback.timestamp.desc()).all()
        
    return render_template("admin_feedback.html", feedbacks=feedbacks)


@app.route('/admin/feedback/<int:id>/reply', methods=['POST'])
def reply_to_feedback(id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    reply = request.form.get('reply', '').strip()
    feedback = Feedback.query.get_or_404(id)
    if not reply:
        flash('Please write a reply before sending it.', 'warning')
        return redirect(url_for('admin_feedback'))
    feedback.admin_response = reply
    feedback.responded_at = datetime.now()
    db.session.commit()
    notify_student_of_admin_reply(feedback.user_id, reply, 'AU Daily: reply to your feedback', 'feedback')
    flash('Reply sent to the student.')
    return redirect(url_for('admin_feedback'))

@app.route('/admin/reports')
def admin_reports():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
        
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


@app.route('/admin/reports/<int:id>/reply', methods=['POST'])
def reply_to_report(id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    reply = request.form.get('reply', '').strip()
    report = Report.query.get_or_404(id)
    if not report.user_id:
        flash('Anonymous reports cannot receive an admin reply.', 'warning')
        return redirect(url_for('admin_reports'))
    if not reply:
        flash('Please write a reply before sending it.', 'warning')
        return redirect(url_for('admin_reports'))
    report.admin_response = reply
    report.responded_at = datetime.now()
    db.session.commit()
    notify_student_of_admin_reply(report.user_id, reply, 'AU Daily: reply to your report', 'report')
    flash('Reply sent to the student.')
    return redirect(url_for('admin_reports'))


@app.route('/admin/reports/<int:id>/status', methods=['POST'])
def update_report_status(id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    status = request.form.get('status', '')
    if status not in {'Pending', 'In Progress', 'Resolved'}:
        flash('Invalid report status.', 'warning')
        return redirect(url_for('admin_reports'))
    report = Report.query.get_or_404(id)
    report.status = status
    db.session.commit()
    flash('Report status updated.')
    return redirect(url_for('admin_reports'))


@app.route('/admin/reports/<int:id>/action', methods=['POST'])
def action_report(id):
    """Delete a reported item only when its type is known to the application."""
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    report = Report.query.get_or_404(id)
    if request.form.get('action') != 'delete_post':
        flash('Unsupported report action.', 'warning')
        return redirect(url_for('admin_reports'))

    models = {'Event': Event, 'NewsPost': NewsPost, 'JobPost': JobPost}
    target_model = models.get(report.item_type)
    target = target_model.query.get(report.item_id) if target_model and report.item_id else None
    if not target:
        flash('The reported item is no longer available.', 'warning')
        return redirect(url_for('admin_reports'))

    db.session.delete(target)
    report.status = 'Resolved'
    db.session.commit()
    flash('Reported item deleted and report resolved.')
    return redirect(url_for('admin_reports'))

@app.route('/admin/resolve_report/<int:report_id>', methods=['POST'])
@require_csrf
def resolve_report(report_id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
        
    report = Report.query.get_or_404(report_id)
    report.status = 'Resolved'
    db.session.commit()
    flash("Report marked as resolved.")
    return redirect(url_for('admin_reports'))

@app.route('/admin/export_students')
def export_students():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

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

@app.route('/admin/upload_allowed_students', methods=['POST'])
def upload_allowed_students():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('admin_dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('admin_dashboard'))

    if file and file.filename.endswith('.csv'):
        # Save the file to root path, overwriting existing
        csv_path = os.path.join(app.root_path, 'allowed_students.csv')
        try:
            file.save(csv_path)
        except Exception as e:
            flash(f"Error saving file: {e}")
            return redirect(url_for('admin_dashboard'))
        
        # Run update logic (same as update_allowed_ids.py)
        allowed_ids = []
        # We try multiple encodings because CSV files saved on different OSes (Windows/Mac) use different encodings
        encodings = ['utf-8-sig', 'cp1252', 'latin-1']
        success = False
        read_error = None # To store a potential error message
        
        # Check for Excel file disguised as CSV
        # 'PK' is the magic number (file signature) for ZIP archives, which .xlsx files are based on
        try:
            with open(csv_path, 'rb') as f:
                if f.read(2) == b'PK':
                    flash("Error: The uploaded file appears to be an Excel .xlsx file saved with .csv extension. Please save as CSV (Comma delimited).")
                    return redirect(url_for('admin_dashboard'))
        except OSError:
            pass

        for encoding in encodings:
            try:
                with open(csv_path, 'r', encoding=encoding, newline='') as f:
                    reader = csv.reader(f)
                    temp_ids = []
                    row_count = 0
                    for row in reader:
                        row_count += 1
                        if row and len(row) > 0:
                            val = row[0].strip()
                            if val:
                                # Split by whitespace and take first part to handle "ID Name" formats
                                potential_id = val.split()[0]
                                # Skip headers like "ID", "Student", or "Registration"
                                if potential_id.lower() not in ['id', 'student', 'registration', 'reg', 'no']:
                                    temp_ids.append(potential_id)
                    
                    # If we found IDs, we are done.
                    if temp_ids:
                        allowed_ids = temp_ids
                        success = True
                        break
                    # If we read rows but found no IDs, it's a format error.
                    elif row_count > 0:
                        read_error = "The CSV was read, but no valid student IDs were found. Ensure IDs are numeric and in the first column, not just a header."
                        break

            except UnicodeDecodeError:
                continue # Try next encoding
            except (PermissionError, IOError) as e:
                read_error = f"Could not read the file. Please check permissions or if it's open elsewhere. Error: {e}"
                break # A file system error is fatal
        
        if not success:
            # Use the specific error if we have one, otherwise a generic one.
            if read_error:
                flash(read_error)
            else:
                flash("Error: Could not read IDs from CSV. The file might be empty or have an unsupported encoding.")
            return redirect(url_for('admin_dashboard'))

        added_count = 0
        # Deduplicate the list to avoid IntegrityErrors in the same session
        unique_ids = list(set(allowed_ids))
        
        for s_id in unique_ids:
            if not AllowedStudent.query.filter_by(student_id=s_id).first():
                db.session.add(AllowedStudent(student_id=s_id))
                added_count += 1
                
        db.session.commit()
        flash(f"Success! {added_count} new allowed student IDs added.")
    else:
        flash('Invalid file type. Please upload a CSV file.')

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/allowed_students')
def view_allowed_students():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    
    page = request.args.get('page', 1, type=int)
    search_q = request.args.get('q', '')
    
    query = AllowedStudent.query
    if search_q:
        query = query.filter(AllowedStudent.student_id.ilike(f'%{search_q}%'))
        
    pagination = query.order_by(AllowedStudent.student_id).paginate(page=page, per_page=50, error_out=False)
    allowed_students = pagination.items
    
    return render_template("allowed_students_list.html", allowed_students=allowed_students, pagination=pagination, search_q=search_q)

@app.route('/admin/add_allowed_student', methods=['POST'])
def add_allowed_student():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    
    student_id = request.form.get('student_id')
    if student_id:
        student_id = student_id.strip()
        if not AllowedStudent.query.filter_by(student_id=student_id).first():
            db.session.add(AllowedStudent(student_id=student_id))
            db.session.commit()
            
            # Try to append to CSV for persistence
            csv_path = os.path.join(app.root_path, 'allowed_students.csv')
            if os.path.exists(csv_path):
                try:
                    with open(csv_path, 'a', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow([student_id])
                except:
                    pass
            flash(f"Student ID {student_id} added successfully.")
        else:
            flash(f"Student ID {student_id} is already allowed.")
    
    return redirect(url_for('view_allowed_students'))

@app.route('/admin/delete_allowed_student/<int:id>', methods=['POST'])
@require_csrf
def delete_allowed_student(id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    
    student = AllowedStudent.query.get_or_404(id)
    s_id = student.student_id
    db.session.delete(student)
    db.session.commit()
    
    # Attempt to remove from CSV to maintain consistency
    csv_path = os.path.join(app.root_path, 'allowed_students.csv')
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
    return redirect(url_for('view_allowed_students'))

@app.route('/admin/delete_allowed_students_bulk', methods=['POST'])
@require_csrf
def delete_allowed_students_bulk():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    
    ids_to_delete = request.form.getlist('student_ids')
    if not ids_to_delete:
        flash("No students selected for deletion.")
        return redirect(url_for('view_allowed_students'))
    
    # Fetch objects to get the actual student_id strings (for CSV removal)
    students = AllowedStudent.query.filter(AllowedStudent.id.in_(ids_to_delete)).all()
    student_id_strings = {s.student_id for s in students}
    
    # Delete from DB
    for student in students:
        db.session.delete(student)
    db.session.commit()
    
    # Update CSV
    csv_path = os.path.join(app.root_path, 'allowed_students.csv')
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
    return redirect(url_for('view_allowed_students'))

# =========================
# ADD EVENT
# =========================

@app.route('/add_event', methods=['GET','POST'])
def add_event():

    if 'admin' not in session and 'student' not in session:
        return redirect(url_for('student_login'))

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
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
            else:
                flash("Invalid file type. Please upload an image or video.")
                return redirect(url_for('add_event')) # Ensure redirect on error

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
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('home'))

    return render_template("add_event.html", departments=DEPARTMENTS)

@app.route('/edit_event/<int:event_id>', methods=['GET', 'POST'])
def edit_event(event_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    event = Event.query.get_or_404(event_id)
    
    # Authorization Check
    if 'student' in session:
        student = Student.query.filter_by(student_id=session['student']).first()
        # Users can only edit events they posted (check by ID)
        if not student or event.user_id != student.student_id:
            flash("You are not authorized to edit this event.")
            return redirect(url_for('home'))
    
    if request.method == 'POST':
        event.title = request.form['title']
        event.description = request.form['description']
        event.date = request.form['date']
        event.department = request.form['department']
        
        image = request.files.get('image')
        if image and image.filename != '':
            if allowed_media_file(image.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                event.image_file = filename
            else:
                flash("Invalid file type.")
                return redirect(request.url)
        
        db.session.commit()
        flash("Event updated successfully!")
        
        if 'admin' in session:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('student_profile'))

    return render_template("edit_event.html", event=event, departments=DEPARTMENTS)

@app.route('/edit_event_description/<int:event_id>', methods=['POST'])
def edit_event_description(event_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    event = Event.query.get_or_404(event_id)
    
    # Authorization Check
    if 'student' in session:
        student = Student.query.filter_by(student_id=session['student']).first()
        if not student or event.user_id != student.student_id:
            flash("You are not authorized to edit this event.")
            return redirect(url_for('home'))
            
    new_desc = request.form.get('description')
    if new_desc and new_desc.strip():
        event.description = new_desc.strip()
        db.session.commit()
        
    return redirect(request.referrer or url_for('home'))

# =========================
# DELETE EVENT
# =========================

@app.route('/delete_event/<int:id>', methods=['POST'])
@require_csrf
def delete_event(id):

    if 'admin' not in session and 'student' not in session:
        return redirect(url_for('student_login'))

    event = Event.query.get_or_404(id)

    # Authorization Check
    if 'student' in session:
        # Users can only delete events they posted (check by ID)
        if event.user_id != session['student']:
            flash("You are not authorized to delete this event.")
            return redirect(url_for('home'))

    remove_uploaded_media(event.image_file)
    db.session.delete(event)
    db.session.commit()
    flash("Event deleted successfully.")

    return redirect(request.referrer or url_for('home'))


# =========================
# STUDENT REGISTER
# =========================

@app.route('/student/register', methods=['GET','POST'])
@require_csrf
def student_register():

    if request.method == "POST":

        student_id = request.form['student_id'].strip()

        # 1. Check if the student_id is in the allowed list
        if not AllowedStudent.query.filter_by(student_id=student_id).first():
            flash("Only AU students can register")
            return redirect(url_for('student_register'))

        # 2. Check if this student_id is already registered
        if Student.query.filter_by(student_id=student_id).first():
            flash("This registration number has already been registered.")
            return redirect(url_for('student_register'))

        name = request.form.get('name')
        department = request.form.get('department')
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone')
        
        if not email or not phone:
            flash("Email and Phone number are required.")
            return redirect(url_for('student_register'))

        # Safely convert graduation_year to integer
        grad_year_str = request.form.get('graduation_year')
        graduation_year = None
        if grad_year_str and grad_year_str.isdigit():
            graduation_year = int(grad_year_str)

        if Student.query.filter_by(email=email).first():
            flash("This email address is already registered.")
            return redirect(url_for('student_register'))

        raw_password = request.form.get('password')
        if request.form.get('privacy_consent') != 'yes':
            flash("Please accept the Privacy Policy to create an account.")
            return redirect(url_for('student_register'))
        if not valid_password(raw_password):
            flash("Password must be at least 10 characters and include both letters and numbers.")
            return redirect(url_for('student_register'))
        if not name or not name.strip() or department not in DEPARTMENTS or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            flash("Enter a valid name, department, and email address.")
            return redirect(url_for('student_register'))
        phone = normalize_indian_mobile(phone)
        if not phone:
            flash("Enter a valid 10-digit Indian mobile number.")
            return redirect(url_for('student_register'))
        password = generate_password_hash(raw_password)

        # Handle Profile Pic
        profile_pic = request.files.get('profile_pic')
        pic_filename = None
        if profile_pic and profile_pic.filename != '':
            if allowed_media_file(profile_pic.filename) and profile_pic.filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS:
                pic_filename = f"{uuid.uuid4().hex}_{secure_filename(profile_pic.filename)}"
                profile_pic.save(os.path.join(app.config['UPLOAD_FOLDER'], pic_filename))

        student = Student(
            student_id=student_id,
            name=name,
            department=department,
            graduation_year=graduation_year,
            email=email,
            phone=phone,
            password=password,
            profile_pic=pic_filename
        )

        db.session.add(student)
        db.session.commit()

        flash("Registration successful! Please login.")
        return redirect(url_for('student_login'))

    return render_template("student_register.html", departments=DEPARTMENTS)


# =========================
# STUDENT LOGIN
# =========================

@app.route('/student/login', methods=['GET','POST'])
@require_csrf
def student_login():
    if 'admin' in session:
        return redirect(url_for('admin_dashboard'))
    if 'student' in session:
        return redirect(url_for('home'))

    if request.method == "POST":
        identifier = request.form.get('student_id', '').strip()
        password = request.form.get('password', '')
        rate_key = login_rate_limit_key(f'student:{identifier}')

        if login_is_rate_limited(rate_key):
            flash('Too many sign-in attempts. Please wait 15 minutes and try again.')
            return render_template("student_login.html"), 429

        student = Student.query.filter(
            or_(Student.student_id == identifier, func.lower(Student.email) == identifier.lower())
        ).first()

        if student and password and verify_password_and_upgrade(student, password):
            clear_login_rate_limit(rate_key)
            session.clear()
            session['student'] = student.student_id
            return redirect(url_for('home'))
        else:
            record_failed_login(rate_key)
            flash("Invalid ID/Email or Password")

    return render_template("student_login.html")


@app.route('/student/admin-recovery', methods=['GET', 'POST'])
@require_csrf
def request_admin_recovery():
    if request.method == 'POST':
        ip_address = request.remote_addr or 'unknown'
        recovery_rate_key = f'admin-recovery:{ip_address}'
        if rate_limit_reached(recovery_rate_key, limit=1, window=timedelta(minutes=5)):
            flash('Please wait five minutes before submitting another recovery request.', 'warning')
            return redirect(url_for('request_admin_recovery'))

        student_id = request.form.get('student_id', '').strip()
        contact_note = request.form.get('contact_note', '').strip()
        if not student_id:
            flash('Enter your student ID to request administrator assistance.', 'warning')
            return redirect(url_for('request_admin_recovery'))

        pending_request = RecoveryRequest.query.filter_by(student_id=student_id, status='Pending').first()
        if pending_request:
            pending_request.contact_note = contact_note[:255]
            pending_request.created_at = datetime.now()
        else:
            db.session.add(RecoveryRequest(student_id=student_id, contact_note=contact_note[:255]))
            create_admin_notification(
                'recovery',
                f'Password recovery request for student {student_id}.',
                'admin_recovery_requests',
            )
        db.session.commit()
        record_rate_limit_attempt(recovery_rate_key, window=timedelta(minutes=5))
        flash('Your request was sent. Contact the administrator through your university’s official channel to verify your identity.', 'success')
        return redirect(url_for('student_login'))

    return render_template('admin_recovery.html')


@app.route('/student/forgot-password', methods=['GET', 'POST'])
@require_csrf
def forgot_password():
    if request.method == 'POST':
        if password_reset_is_rate_limited():
            flash('Too many reset requests. Please wait and try again.', 'warning')
            return redirect(url_for('forgot_password'))
        email = request.form.get('email', '').strip().lower()
        student = Student.query.filter(func.lower(Student.email) == email).first() if email else None

        # Keep the response identical whether or not an account exists.
        flash('If an account matches those details, a password reset link has been sent.')
        if student and student.email:
            token = password_reset_serializer.dumps({
                'student_id': student.student_id,
                'password_hash': student.password,
            })
            reset_url = public_url_for('reset_password', token=token)
            try:
                message = Message(
                    subject='AU Daily password reset',
                    recipients=[student.email],
                    html=render_template('reset_password_email.html', reset_url=reset_url, name=student.name),
                )
                mail.send(message)
            except Exception:
                app.logger.exception('Unable to send password reset email')
                flash('The reset email could not be sent. Please contact the administrator.', 'warning')
        return redirect(url_for('student_login'))

    return render_template('forgot_password.html')


@app.route('/student/phone-recovery', methods=['GET', 'POST'])
@require_csrf
def phone_recovery():
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        mobile = normalize_indian_mobile(request.form.get('phone', ''))
        student = Student.query.filter_by(student_id=student_id).first() if student_id else None
        registered_mobile = normalize_indian_mobile(student.phone) if student else None

        if not student or not mobile or mobile != registered_mobile:
            flash('The Student ID and registered mobile number do not match our records.', 'warning')
            return redirect(url_for('phone_recovery'))
        if not FAST2SMS_API_KEY or not FAST2SMS_OTP_ID:
            flash('Phone recovery is temporarily unavailable. Please contact the administrator.', 'warning')
            return redirect(url_for('phone_recovery'))

        now = datetime.now()
        attempt = PhoneRecoveryAttempt.query.filter_by(student_id=student.student_id).first()
        if not attempt:
            attempt = PhoneRecoveryAttempt(student_id=student.student_id, window_started_at=now)
            db.session.add(attempt)
        if attempt.locked_until and attempt.locked_until > now:
            flash('Too many incorrect codes. Please wait 15 minutes before trying again.', 'warning')
            return redirect(url_for('phone_recovery'))
        if attempt.last_sent_at and now - attempt.last_sent_at < timedelta(minutes=1):
            flash('Please wait one minute before requesting another OTP.', 'warning')
            return redirect(url_for('phone_recovery'))
        if not attempt.window_started_at or now - attempt.window_started_at >= timedelta(minutes=15):
            attempt.window_started_at, attempt.send_count, attempt.failed_verifications = now, 0, 0
        if attempt.send_count >= 3:
            attempt.locked_until = now + timedelta(minutes=15)
            db.session.commit()
            flash('Too many OTP requests. Please wait 15 minutes before trying again.', 'warning')
            return redirect(url_for('phone_recovery'))

        result = fast2sms_otp_request('send', {'otp_id': FAST2SMS_OTP_ID, 'mobile': mobile})
        if not result.get('return'):
            flash('We could not send an OTP right now. Please try again later.', 'warning')
            return redirect(url_for('phone_recovery'))
        attempt.last_sent_at = now
        attempt.send_count += 1
        db.session.commit()
        session['phone_recovery_student_id'] = student.student_id
        session['phone_recovery_mobile'] = mobile
        session.pop('phone_recovery_verified', None)
        flash('OTP sent to your registered mobile number.')
        return redirect(url_for('verify_phone_recovery'))

    return render_template('phone_recovery.html', configured=bool(FAST2SMS_API_KEY and FAST2SMS_OTP_ID))


@app.route('/student/phone-recovery/verify', methods=['GET', 'POST'])
@require_csrf
def verify_phone_recovery():
    student_id = session.get('phone_recovery_student_id')
    mobile = session.get('phone_recovery_mobile')
    if not student_id or not mobile:
        flash('Start phone recovery again to receive a new OTP.', 'warning')
        return redirect(url_for('phone_recovery'))

    if request.method == 'POST':
        otp = re.sub(r'\D', '', request.form.get('otp', ''))
        attempt = PhoneRecoveryAttempt.query.filter_by(student_id=student_id).first()
        now = datetime.now()
        if not attempt or (attempt.locked_until and attempt.locked_until > now):
            flash('This recovery request is locked or expired. Start again later.', 'warning')
            return redirect(url_for('phone_recovery'))
        if len(otp) < 4:
            flash('Enter the OTP sent to your mobile number.', 'warning')
            return redirect(url_for('verify_phone_recovery'))
        result = fast2sms_otp_request('verify', {'mobile': mobile, 'otp': otp})
        if not result.get('return'):
            attempt.failed_verifications += 1
            if attempt.failed_verifications >= 5:
                attempt.locked_until = now + timedelta(minutes=15)
            db.session.commit()
            flash('Invalid OTP. Please try again.', 'warning')
            return redirect(url_for('verify_phone_recovery'))
        attempt.failed_verifications = 0
        db.session.commit()
        session['phone_recovery_verified'] = True
        return redirect(url_for('reset_password_by_phone'))

    return render_template('verify_phone_otp.html', mobile=f'******{mobile[-4:]}')


@app.route('/student/phone-recovery/reset', methods=['GET', 'POST'])
@require_csrf
def reset_password_by_phone():
    student_id = session.get('phone_recovery_student_id')
    if not student_id or not session.get('phone_recovery_verified'):
        flash('Verify your phone OTP before resetting the password.', 'warning')
        return redirect(url_for('phone_recovery'))
    student = Student.query.filter_by(student_id=student_id).first()
    if not student:
        session.pop('phone_recovery_student_id', None)
        session.pop('phone_recovery_mobile', None)
        session.pop('phone_recovery_verified', None)
        return redirect(url_for('phone_recovery'))
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
            return redirect(url_for('student_login'))
    return render_template('phone_reset_password.html')


@app.route('/student/reset-password/<token>', methods=['GET', 'POST'])
@require_csrf
def reset_password(token):
    try:
        data = password_reset_serializer.loads(token, max_age=15 * 60)
    except (BadSignature, SignatureExpired):
        flash('This password reset link is invalid or has expired.')
        return redirect(url_for('forgot_password'))

    student = Student.query.filter_by(student_id=data.get('student_id')).first()
    if not student or not hmac.compare_digest(student.password or '', data.get('password_hash', '')):
        flash('This password reset link is no longer valid.')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not valid_password(password):
            flash('Your new password must be at least 10 characters and include letters and numbers.')
        elif password != confirm_password:
            flash('The passwords do not match.')
        else:
            student.password = generate_password_hash(password)
            db.session.commit()
            flash('Password updated. You can now sign in.')
            return redirect(url_for('student_login'))

    return render_template('reset_password.html', token=token)


# =========================
# STUDENT PROFILE
# =========================

@app.route('/profile/<string:student_id>')
def view_profile(student_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

    student = Student.query.filter_by(student_id=student_id).first()
    
    if not student:
        admin = Admin.query.filter_by(admin_id=student_id).first()
        if not admin and student_id not in ["None", "Admin", "admin"]:
            flash("Profile not found.")
            return redirect(request.referrer or url_for('home'))
            
        class MockAdmin:
            def __init__(self):
                self.student_id = admin.admin_id if admin else "Admin"
                self.name = "Administrator"
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

    return render_template("view_profile.html", 
                           student=student, 
                           events=events, 
                           news_posts=news_posts,
                           follower_count=follower_count,
                           following_count=following_count,
                           is_following=is_following,
                           current_user_id=current_user_id)

@app.route('/student/dashboard')
def student_dashboard():
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    student_id = session['student']
    student = Student.query.filter_by(student_id=student_id).first()
    
    total_tasks = Task.query.filter_by(user_id=student_id).count()
    completed_tasks = Task.query.filter_by(user_id=student_id, is_completed=True).count()
    pending_tasks = total_tasks - completed_tasks
    
    events_registered = EventRegistration.query.filter_by(user_id=student_id).count()
    polls_voted = PollVote.query.filter_by(user_id=student_id).count()
    doubts_asked = AnonymousDoubt.query.filter_by(user_id=student_id).count()
    doubts_replied = DoubtReply.query.filter_by(user_id=student_id).count()

    # Chart Data: Last 6 months of workload activity
    chart_labels = []
    chart_tasks = []
    
    today = datetime.now()
    for i in range(5, -1, -1):
        m = (today.month - i - 1) % 12 + 1
        y = today.year + ((today.month - i - 1) // 12)
        chart_labels.append(f"{calendar.month_abbr[m]} {y}")
        t_count = Task.query.filter_by(user_id=student_id).filter(func.extract('month', Task.timestamp) == m, func.extract('year', Task.timestamp) == y).count()
        chart_tasks.append(t_count)
    
    return render_template("student_dashboard.html", 
                           student=student,
                           total_tasks=total_tasks, completed_tasks=completed_tasks, pending_tasks=pending_tasks,
                           events_registered=events_registered, polls_voted=polls_voted,
                           doubts_asked=doubts_asked, doubts_replied=doubts_replied,
                           chart_labels=chart_labels, chart_tasks=chart_tasks)

@app.route('/api/user_preview/<string:student_id>')
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
        <h6 class="fw-bold mb-1 text-truncate">{escape(student.name)}</h6>
        <p class="small text-muted mb-3"><span class="badge bg-light text-dark border">{escape(student.department)}</span></p>
        <a href="/profile/{student.student_id}" class="btn btn-sm btn-primary rounded-pill px-4">View Profile</a>
    </div>
    """
    return html

@app.route('/student/profile')
def student_profile():
    if 'student' not in session:
        return redirect(url_for('student_login'))

    # Redirect to the new generic profile view for the logged-in user
    return redirect(url_for('view_profile', student_id=session['student']))

@app.route('/profile/<string:student_id>/<string:list_type>')
def followers_list(student_id, list_type):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    user = Student.query.filter_by(student_id=student_id).first()
    if not user:
        admin = Admin.query.filter_by(admin_id=student_id).first()
        if not admin and student_id not in ["None", "Admin", "admin"]:
            flash("Profile not found.")
            return redirect(request.referrer or url_for('home'))
            
        class MockAdmin:
            def __init__(self):
                self.student_id = admin.admin_id if admin else "Admin"
                self.name = "Administrator"
                self.profile_pic = None
                self.is_admin_profile = True
        user = MockAdmin()
    
    if list_type == 'followers':
        user_ids = db.session.query(Follower.follower_id).filter_by(followed_id=student_id).all()
        title = "Followers"
    elif list_type == 'following':
        user_ids = db.session.query(Follower.followed_id).filter_by(follower_id=student_id).all()
        title = "Following"
    else:
        return "Invalid list type", 404
        
    ids = [u[0] for u in user_ids]
    users_list = Student.query.filter(Student.student_id.in_(ids)).all() if ids else []
    
    current_user_id = session.get('student')
    if current_user_id:
        for u in users_list:
            u.is_self = (u.student_id == current_user_id)
            if not u.is_self:
                u.is_following = Follower.query.filter_by(follower_id=current_user_id, followed_id=u.student_id).first() is not None

    return render_template("followers.html", users_list=users_list, title=title, main_user=user)

@app.route('/student/settings', methods=['GET', 'POST'])
def student_settings():
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    student = Student.query.filter_by(student_id=session['student']).first()
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_info':
            new_email = request.form.get('email')
            # Check uniqueness if email changed
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
                
        return redirect(url_for('student_settings'))

    return render_template("student_settings.html", student=student)
    
@app.route('/student/update_pic', methods=['POST'])
def update_profile_pic():
    wants_json = request.accept_mimetypes.best == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if 'student' not in session:
        if wants_json:
            return jsonify(success=False, message="Please sign in again."), 401
        return redirect(url_for('student_login'))
    
    student = Student.query.filter_by(student_id=session['student']).first()
    if not student:
        flash("Profile not found.")
        if wants_json:
            return jsonify(success=False, message="Profile not found."), 404
        return redirect(url_for('home'))

    image = request.files.get('profile_pic')
    
    if image and image.filename != '':
        image_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if allowed_media_file(image.filename) and image.filename.rsplit('.', 1)[1].lower() in image_extensions:
            # Generate clean filename with extension
            ext = image.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            new_file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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
                app.logger.exception("Profile picture update failed")
                if wants_json:
                    return jsonify(success=False, message="Could not save the photo. Please try a smaller JPG or PNG image."), 500
                flash("Could not save the photo. Please try a smaller JPG or PNG image.")
                return redirect(request.referrer or url_for('student_settings'))

            if old_filename:
                old_file_path = os.path.join(app.config['UPLOAD_FOLDER'], old_filename)
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
        flash("Please select an image file first.")
        if wants_json:
            return jsonify(success=False, message="Please select an image file first."), 400

    return redirect(request.referrer or url_for('student_settings'))

@app.route('/student/remove_pic', methods=['POST'])
def remove_profile_pic():
    if 'student' not in session:
        return redirect(url_for('student_login'))
        
    student = Student.query.filter_by(student_id=session['student']).first()
    if student.profile_pic:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], student.profile_pic)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        student.profile_pic = None
        db.session.commit()
        flash("Profile picture removed.")
        
    return redirect(request.referrer or url_for('student_settings'))

@app.route('/follow/<string:student_id>', methods=['POST'])
@require_csrf
def follow_user(student_id):
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    current_user_id = session['student']
    if current_user_id == student_id:
        flash("You cannot follow yourself.")
        return redirect(request.referrer or url_for('home'))

    existing_follow = Follower.query.filter_by(follower_id=current_user_id, followed_id=student_id).first()

    if existing_follow:
        db.session.delete(existing_follow)
        flash(f"You have unfollowed this user.")
    else:
        new_follow = Follower(follower_id=current_user_id, followed_id=student_id)
        db.session.add(new_follow)
        flash(f"You are now following this user.")
    
    db.session.commit()
    return redirect(request.referrer or url_for('home'))

@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    if request.method == 'POST':
        content = request.form.get('content')
        if content and content.strip():
            new_feedback = Feedback(user_id=session['student'], content=content)
            db.session.add(new_feedback)
            create_admin_notification(
                'feedback',
                f'New feedback from student {session["student"]}.',
                'admin_feedback',
            )
            db.session.commit()
            send_admin_alert(
                'AU Daily: new student feedback',
                'New student feedback',
                {'Student ID': session['student'], 'Feedback': content.strip()},
            )
            flash("Thank you! Your feedback has been submitted.")
            return redirect(url_for('home'))
        else:
            flash("Please write something before submitting.")
            
    return render_template("feedback.html")

@app.route('/submit_report', methods=['GET', 'POST'])
def submit_report():
    if 'student' not in session:
        return redirect(url_for('student_login'))

    if request.method == 'GET':
        return render_template('submit_report.html')
    
    report_type = request.form.get('report_type')
    description = request.form.get('description')
    item_type = request.form.get('item_type')
    item_id = request.form.get('item_id')
    screenshot = request.files.get('screenshot')
    screenshot_filename = None
    
    valid_report_types = {'Spam', 'Fake Job', 'Abuse', 'Bug', 'Other'}
    if report_type in valid_report_types and description and description.strip():
        if screenshot and screenshot.filename != '':
            if allowed_media_file(screenshot.filename) and screenshot.filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS:
                screenshot_filename = f"{uuid.uuid4().hex}_{secure_filename(screenshot.filename)}"
                screenshot.save(os.path.join(app.config['UPLOAD_FOLDER'], screenshot_filename))
            else:
                flash("Invalid screenshot file type.")
                return redirect(request.referrer or url_for('home'))

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
            'admin_reports',
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
    else:
        flash('Please select an issue type and describe the problem.', 'warning')

    return redirect(safe_redirect_target(url_for('home')))

# =========================
# PRIVATE MESSAGING
# =========================

@app.route('/messages')
def inbox():
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    current_user = session['student']
    
    # Get all messages involving the current user to find unique conversations
    messages = PrivateMessage.query.filter(
        or_(PrivateMessage.sender_id == current_user, PrivateMessage.receiver_id == current_user)
    ).order_by(PrivateMessage.timestamp.desc()).all()
    
    conversations = {}
    for msg in messages:
        other_user_id = msg.receiver_id if msg.sender_id == current_user else msg.sender_id
        if other_user_id not in conversations:
            other_student = Student.query.filter_by(student_id=other_user_id).first()
            if other_student:
                conversations[other_user_id] = {
                    'user': other_student,
                    'latest_msg': msg,
                    'unread_count': 0
                }
        if msg.receiver_id == current_user and not msg.is_read:
            if other_user_id in conversations:
                conversations[other_user_id]['unread_count'] += 1
                
    return render_template("inbox.html", conversations=conversations.values())

@app.route('/chat/<string:student_id>', methods=['GET', 'POST'])
def chat(student_id):
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    current_user = session['student']
    if current_user == student_id:
        flash("You cannot chat with yourself.")
        return redirect(url_for('inbox'))
        
    other_user = Student.query.filter_by(student_id=student_id).first_or_404()
    
    # Handle Sending New Message
    if request.method == 'POST':
        content = request.form.get('content', '')
        image = request.files.get('image')
        image_filename = None
        
        if image and image.filename != '':
            if allowed_media_file(image.filename):
                image_filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                
        if content.strip() or image_filename:
            new_msg = PrivateMessage(sender_id=current_user, receiver_id=student_id, content=content.strip(), image_file=image_filename)
            db.session.add(new_msg)
            db.session.commit()
            return redirect(url_for('chat', student_id=student_id))
            
    # Mark unread messages as read when opening chat
    unread_msgs = PrivateMessage.query.filter_by(sender_id=student_id, receiver_id=current_user, is_read=False).all()
    for msg in unread_msgs:
        msg.is_read = True
    if unread_msgs:
        db.session.commit()
        
    # Get Chat History
    messages = PrivateMessage.query.filter(
        or_(
            (PrivateMessage.sender_id == current_user) & (PrivateMessage.receiver_id == student_id),
            (PrivateMessage.sender_id == student_id) & (PrivateMessage.receiver_id == current_user)
        )
    ).order_by(PrivateMessage.timestamp.asc()).all()
    
    return render_template("chat.html", other_user=other_user, messages=messages, current_user=current_user)

@app.route('/delete_message/<int:message_id>', methods=['POST'])
@require_csrf
def delete_message(message_id):
    if 'student' not in session:
        return redirect(url_for('student_login'))
        
    msg = PrivateMessage.query.get_or_404(message_id)
    if msg.sender_id == session['student']:
        if msg.image_file:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], msg.image_file)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        db.session.delete(msg)
        db.session.commit()
        
    return redirect(request.referrer or url_for('inbox'))

# =========================
# LOGOUT
# =========================

@app.route('/logout', methods=['POST'])
@require_csrf
def logout():

    session.clear()

    return redirect(url_for('home'))

# =========================
# STUDENT UTILITIES (CALCULATOR)
# =========================

@app.route('/gpa_calculator')
def gpa_calculator():
    if 'student' not in session:
        return redirect(url_for('student_login'))
    return render_template("gpa_calculator.html")

@app.route('/planner')
def planner():
    if 'student' not in session:
        return redirect(url_for('student_login'))
    
    tasks = Task.query.filter_by(user_id=session['student']).order_by(Task.is_completed.asc(), Task.timestamp.desc()).all()
    return render_template("planner.html", tasks=tasks)

@app.route('/add_task', methods=['POST'])
def add_task():
    if 'student' not in session:
        return redirect(url_for('student_login'))
        
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
    return redirect(url_for('planner'))

@app.route('/toggle_task/<int:task_id>', methods=['POST'])
@require_csrf
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    if 'student' in session and task.user_id == session['student']:
        task.is_completed = not task.is_completed
        db.session.commit()
    return redirect(url_for('planner'))

@app.route('/delete_task/<int:task_id>', methods=['POST'])
@require_csrf
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    if 'student' in session and task.user_id == session['student']:
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for('planner'))

# =========================
# ACADEMIC RESOURCES HUB
# =========================

@app.route('/resources')
def resources():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
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

@app.route('/add_resource', methods=['POST'])
def add_resource():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    title = request.form.get('title')
    subject = request.form.get('subject')
    department = request.form.get('department')
    year = request.form.get('year')
    file = request.files.get('file')

    # Validation
    if not all([title, subject, department, year]) or not title.strip() or not subject.strip():
        flash("All fields (Title, Subject, Dept, Year) are required.")
        return redirect(url_for('resources'))
    if department not in DEPARTMENTS or year not in {'1st Year', '2nd Year', '3rd Year', '4th Year', 'All Years'}:
        flash("Choose a valid department and year.")
        return redirect(url_for('resources'))

    if not file or file.filename == '':
        flash("No file selected for upload. Please choose a file.")
        return redirect(url_for('resources'))

    if file:
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else None

        if ext and ext in app.config['RESOURCE_EXTENSIONS']:
            try:
                # Generate unique, safe filename
                safe_name = secure_filename(file.filename) or f"resource_{uuid.uuid4().hex[:8]}.{ext}"
                unique_filename = f"{uuid.uuid4().hex}_{safe_name}"

                # Ensure directory exists
                os.makedirs(app.config['RESOURCE_FOLDER'], exist_ok=True)

                # The file_path in the DB should only be the filename. The full path is constructed in the template.
                file.save(os.path.join(app.config['RESOURCE_FOLDER'], unique_filename))

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
                return redirect(url_for('resources')) # Ensure redirect on error
        else:
            flash(f"Invalid file format (.{ext if ext else 'None'}). Allowed: {', '.join(app.config['RESOURCE_EXTENSIONS'])}")
            return redirect(url_for('resources')) # Ensure redirect on error
    
    # This final redirect is crucial. It tells the browser the process is complete.
    return redirect(url_for('resources')) 

@app.route('/delete_resource/<int:resource_id>', methods=['POST'])
@require_csrf
def delete_resource(resource_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    resource = Resource.query.get_or_404(resource_id)
    current_user = session.get('student') or session.get('admin')
    
    if resource.user_id == current_user or 'admin' in session:
        file_path = os.path.join(app.config['RESOURCE_FOLDER'], resource.file_path)
        if not os.path.isfile(file_path):
            file_path = os.path.join(app.config['LEGACY_RESOURCE_FOLDER'], os.path.basename(resource.file_path))
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        db.session.delete(resource)
        db.session.commit()
        flash("Resource deleted.")
        
    return redirect(url_for('resources'))

@app.route('/resource/<int:resource_id>/file')
def download_resource_file(resource_id):
    """Serve academic resources only to signed-in campus users."""
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    resource = Resource.query.get_or_404(resource_id)
    filename = os.path.basename(resource.file_path)
    folder = app.config['RESOURCE_FOLDER']
    if not os.path.isfile(os.path.join(folder, filename)):
        folder = app.config['LEGACY_RESOURCE_FOLDER']
    if not os.path.isfile(os.path.join(folder, filename)):
        abort(404)
    return send_from_directory(folder, filename, as_attachment=request.args.get('download') == '1')


@app.route('/resource/<int:resource_id>', methods=['GET', 'POST'])
def view_resource(resource_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
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
            flash("Comment added!")
            return redirect(url_for('view_resource', resource_id=resource_id))

    comments = ResourceComment.query.filter_by(resource_id=resource_id).order_by(ResourceComment.timestamp.desc()).all()
    return render_template("resource_detail.html", resource=resource, comments=comments)

@app.route('/delete_resource_comment/<int:comment_id>', methods=['POST'])
@require_csrf
def delete_resource_comment(comment_id):
    comment = ResourceComment.query.get_or_404(comment_id)
    if 'admin' in session or session.get('student') == comment.user_id:
        db.session.delete(comment)
        db.session.commit()
        flash("Comment deleted.")
    return redirect(safe_redirect_target(url_for('resources')))

@app.route('/toggle_save_resource/<int:resource_id>', methods=['POST'])
@require_csrf
def toggle_save_resource(resource_id):
    if 'student' not in session:
        flash("Please log in to save resources.")
        return redirect(url_for('student_login'))
        
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
    return redirect(safe_redirect_target(url_for('resources')))

@app.route('/saved_resources')
def saved_resources():
    if 'student' not in session:
        return redirect(url_for('student_login'))
        
    user_id = session['student']
    saved_ids = [sr.resource_id for sr in SavedResource.query.filter_by(user_id=user_id).all()]
    resources_list = Resource.query.filter(Resource.id.in_(saved_ids)).all() if saved_ids else []
    
    return render_template("saved_resources.html", resources=resources_list)

# =========================
# CAMPUS GALLERY
# =========================

@app.route('/gallery')
def gallery():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
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
                'date': e.date, # Stored as YYYY-MM-DD string
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
                'date': n.timestamp.strftime('%Y-%m-%d'),
                'type': 'News',
                'media_type': m_type
            })
            
    # Sort by date (newest first)
    gallery_items.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template("gallery.html", images=gallery_items)

# =========================
# CAREER / OPPORTUNITIES
# =========================

@app.route('/opportunities')
def opportunities():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
    
    category_filter = request.args.get('category')
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    query = JobPost.query
    if category_filter:
        query = query.filter_by(category=category_filter)
        
    pagination = query.order_by(JobPost.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    jobs = pagination.items
    
    return render_template("opportunities.html", jobs=jobs, pagination=pagination, categories=JOB_CATEGORIES, current_category=category_filter)

@app.route('/add_opportunity', methods=['POST'])
def add_opportunity():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    title = request.form.get('title')
    company = request.form.get('company')
    category = request.form.get('category')
    description = request.form.get('description')
    link = request.form.get('link')
    image = request.files.get('image') # Get the image file
    
    if title and category:
        if category not in JOB_CATEGORIES:
            flash("Choose a valid opportunity category.")
            return redirect(url_for('opportunities'))
        if not valid_external_url(link):
            flash("The opportunity link must be a complete http:// or https:// URL.")
            return redirect(url_for('opportunities'))
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
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
            else:
                flash("Invalid file type for opportunity image. Only images and videos are allowed.")
                return redirect(url_for('opportunities')) # Ensure redirect on error
                
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
        
    return redirect(url_for('opportunities'))

@app.route('/delete_opportunity/<int:job_id>', methods=['POST'])
@require_csrf
def delete_opportunity(job_id):
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))
        
    job = JobPost.query.get_or_404(job_id)
    current_user = session.get('student') or session.get('admin')
    
    if job.user_id == current_user or 'admin' in session:
        remove_uploaded_media(job.image_file)
        db.session.delete(job)
        db.session.commit()
        flash("Opportunity deleted.")
        
    return redirect(url_for('opportunities'))

# =========================
# GLOBAL SEARCH
# =========================

@app.route('/search')
def global_search():
    if 'student' not in session and 'admin' not in session:
        return redirect(url_for('student_login'))

    query = request.args.get('q', '').strip()
    if not query:
        return redirect(safe_redirect_target(url_for('home')))

    # Search across Events (Title, Description, Department)
    events = Event.query.filter(
        or_(Event.title.ilike(f'%{query}%'), Event.description.ilike(f'%{query}%'), Event.department.ilike(f'%{query}%'))
    ).order_by(Event.id.desc()).all()

    # Search across News Feed content
    news = NewsPost.query.filter(NewsPost.content.ilike(f'%{query}%')).order_by(NewsPost.timestamp.desc()).all()

    # Search for Students (Profiles)
    students = Student.query.filter(
        or_(Student.name.ilike(f'%{query}%'), Student.student_id.ilike(f'%{query}%'), Student.department.ilike(f'%{query}%'))
    ).limit(20).all()

    return render_template("search_results.html", query=query, events=events, news=news, students=students)

# =========================
# STATIC PAGES
# =========================

@app.route('/privacy')
def privacy_policy():
    return render_template("privacy_policy.html")

# =========================
# RUN APP
# =========================

if __name__ == "__main__":
    # In production, debug should be False. We check the environment variable.
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    if is_production and debug_mode:
        raise RuntimeError("FLASK_DEBUG must be disabled in production.")
    # use_reloader=False prevents WinError 10038 on Python 3.13 + Windows
    print("🌟 STARTING NEW SERVER ON PORT 5001 🌟")
    app.run(host='0.0.0.0', port=5001, debug=debug_mode, use_reloader=False)
