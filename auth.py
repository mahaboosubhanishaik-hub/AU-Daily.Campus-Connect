from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, current_app
from sqlalchemy import or_, func
from werkzeug.security import generate_password_hash, check_password_hash
import hmac
import re
from datetime import datetime, timedelta
from flask_mail import Message
from itsdangerous import BadSignature, SignatureExpired

import app as app_module
from app import db, mail
# The models and helpers are defined in the main `app.py` file.
from app import (
    Student, AllowedStudent, AuthRateLimit, RecoveryRequest,
    login_rate_limit_key, login_is_rate_limited, record_failed_login, clear_login_rate_limit,
    password_reset_is_rate_limited, valid_password, normalize_indian_mobile,
    public_url_for, rate_limit_reached, record_rate_limit_attempt,
    create_admin_notification, DEPARTMENTS
)

auth_bp = Blueprint('auth', __name__, template_folder='../templates')

@auth_bp.route('/student/register', methods=['GET','POST'])
def student_register():

    if request.method == "POST":

        student_id = request.form['student_id'].strip()

        if not AllowedStudent.query.filter_by(student_id=student_id).first():
            flash("Only AU students can register")
            return redirect(url_for('auth.student_register'))

        if Student.query.filter_by(student_id=student_id).first():
            flash("This registration number has already been registered.")
            return redirect(url_for('auth.student_register'))

        name = request.form.get('name')
        department = request.form.get('department')
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone')
        
        if not email or not phone:
            flash("Email and Phone number are required.")
            return redirect(url_for('auth.student_register'))

        grad_year_str = request.form.get('graduation_year')
        graduation_year = None
        if grad_year_str and grad_year_str.isdigit():
            graduation_year = int(grad_year_str)

        if Student.query.filter_by(email=email).first():
            flash("This email address is already registered.")
            return redirect(url_for('auth.student_register'))

        raw_password = request.form.get('password')
        if request.form.get('privacy_consent') != 'yes':
            flash("Please accept the Privacy Policy to create an account.")
            return redirect(url_for('auth.student_register'))
        if not valid_password(raw_password):
            flash("Password must be at least 10 characters and include both letters and numbers.")
            return redirect(url_for('auth.student_register'))
        if not name or not name.strip() or department not in DEPARTMENTS or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            flash("Enter a valid name, department, and email address.")
            return redirect(url_for('auth.student_register'))
        phone = normalize_indian_mobile(phone)
        if not phone:
            flash("Enter a valid 10-digit Indian mobile number.")
            return redirect(url_for('auth.student_register'))
        password = generate_password_hash(raw_password)

        student = Student(
            student_id=student_id,
            name=name,
            department=department,
            graduation_year=graduation_year,
            email=email,
            phone=phone,
            password=password,
            profile_pic=None # Profile pic is handled separately
        )

        db.session.add(student)
        db.session.commit()

        flash("Registration successful! Please login.")
        return redirect(url_for('auth.student_login'))

    return render_template("student_register.html", departments=DEPARTMENTS)


@auth_bp.route('/student/login', methods=['GET','POST'])
def student_login():
    if 'admin' in session:
        return redirect(url_for('main.admin_dashboard'))
    if 'student' in session:
        return redirect(url_for('main.home'))

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

        if student and password and g.verify_password_and_upgrade(student, password):
            clear_login_rate_limit(rate_key)
            session.clear()
            session['student'] = student.student_id # This is correct
            return redirect(url_for('main.home'))
        else:
            record_failed_login(rate_key)
            flash("Invalid ID/Email or Password")

    return render_template("student_login.html")


@auth_bp.route('/student/admin-recovery', methods=['GET', 'POST'])
def request_admin_recovery():
    if request.method == 'POST':
        ip_address = request.remote_addr or 'unknown'
        recovery_rate_key = f'admin-recovery:{ip_address}'
        if rate_limit_reached(recovery_rate_key, limit=1, window=timedelta(minutes=5)):
            flash('Please wait five minutes before submitting another recovery request.', 'warning')
            return redirect(url_for('auth.request_admin_recovery'))

        student_id = request.form.get('student_id', '').strip()
        recovery_email = request.form.get('recovery_email', '').strip().lower()
        contact_note = request.form.get('contact_note', '').strip()
        if not student_id:
            flash('Enter your student ID to request administrator assistance.', 'warning')
            return redirect(url_for('auth.request_admin_recovery'))
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', recovery_email):
            flash('Enter a valid email address where the administrator can send your temporary password.', 'warning')
            return redirect(url_for('auth.request_admin_recovery'))
        student = Student.query.filter_by(student_id=student_id).first()
        if not student or (student.email or '').strip().lower() != recovery_email:
            flash('Invalid student ID or registered email. Enter the email used during registration.', 'warning')
            return redirect(url_for('auth.request_admin_recovery'))

        pending_request = RecoveryRequest.query.filter_by(student_id=student_id, status='Pending').first()
        if pending_request:
            pending_request.recovery_email = recovery_email
            pending_request.contact_note = contact_note[:255]
            pending_request.created_at = datetime.now()
        else:
            db.session.add(RecoveryRequest(
                student_id=student_id,
                recovery_email=recovery_email,
                contact_note=contact_note[:255],
            ))
        create_admin_notification(
            'recovery',
            f'Password recovery request for student {student_id} ({recovery_email}).',
            'main.admin_recovery_requests',
        )
        db.session.commit()
        record_rate_limit_attempt(recovery_rate_key, window=timedelta(minutes=5))
        flash('Your request was sent. Contact the administrator through your university’s official channel to verify your identity.', 'success')
        return redirect(url_for('auth.student_login'))

    return render_template('admin_recovery.html')


@auth_bp.route('/student/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        if password_reset_is_rate_limited():
            flash('Too many reset requests. Please wait and try again.', 'warning')
            return redirect(url_for('auth.forgot_password'))
        email = request.form.get('email', '').strip().lower()
        student = Student.query.filter(func.lower(Student.email) == email).first() if email else None

        flash('If an account matches those details, a password reset link has been sent.')
        if student and student.email:
            token = app_module.password_reset_serializer.dumps({
                'student_id': student.student_id,
                'password_hash': student.password,
            })
            reset_url = public_url_for('auth.reset_password', token=token)
            try:
                message = Message(
                    subject='AU Daily password reset',
                    recipients=[student.email],
                    html=render_template('reset_password_email.html', reset_url=reset_url, name=student.name),
                )
                mail.send(message)
            except Exception:
                current_app.logger.exception('Unable to send password reset email')
                flash('The reset email could not be sent. Please contact the administrator.', 'warning')
        return redirect(url_for('auth.student_login'))

    return render_template('forgot_password.html')


@auth_bp.route('/student/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        data = app_module.password_reset_serializer.loads(token, max_age=15 * 60)
    except (BadSignature, SignatureExpired):
        flash('This password reset link is invalid or has expired.')
        return redirect(url_for('auth.forgot_password'))

    student = Student.query.filter_by(student_id=data.get('student_id')).first()
    if not student or not hmac.compare_digest(student.password or '', data.get('password_hash', '')):
        flash('This password reset link is no longer valid.')
        return redirect(url_for('auth.forgot_password'))

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
            return redirect(url_for('auth.student_login'))

    return render_template('reset_password.html', token=token)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    # This route should still be protected by the global CSRF check
    session.clear()
    return redirect(url_for('main.home'))
