import secrets
from datetime import datetime, timedelta
from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_mail import Message # This import is not used in the diff, but kept for other functions in auth.py
from werkzeug.security import generate_password_hash

from app import (
    Admin,
    AllowedStudent,
    DEPARTMENTS,
    EmailVerificationToken,
    mail, # This import is not used in the diff, but kept for other functions in auth.py
    Student,
    RecoveryRequest,
    clear_login_rate_limit,
    create_admin_notification,
    db,
    login_is_rate_limited,
    login_rate_limit_key,
    password_reset_is_rate_limited,
    password_reset_serializer,
    public_url_for,
    record_failed_login, # This import is not used in the diff, but kept for other functions in auth.py
    _handle_login_attempt, # New import for the refactored login logic
    require_csrf,
    Poll,
    csrf_token,
    send_admin_alert,
    valid_password,
)


auth_bp = Blueprint("auth", __name__)

# Add cascade delete for PollVote
Poll.votes = db.relationship('PollVote', backref='poll', cascade="all, delete-orphan")


@auth_bp.route("/student/login", methods=["GET", "POST"])
@require_csrf
def student_login():
    if "student" in session:
        return redirect(url_for("main.home"))
    if "admin" in session:
        return redirect(url_for("main.admin_dashboard"))

    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        password = request.form.get("password", "")
        try:
            return _handle_login_attempt(
                Student, 'student_id', student_id, password,
                "main.home", "Invalid Student ID or Password", "student_login.html", csrf_token,
                lookup_attrs=("student_id", "email")
            )
        except Exception:
            current_app.logger.exception("Student login failed unexpectedly")
            flash("An unexpected error occurred during login. Please try again later.", "danger")
            return render_template("student_login.html", csrf_token=csrf_token), 500

    return render_template("student_login.html", csrf_token=csrf_token)


@auth_bp.route("/student/register", methods=["GET", "POST"])
@require_csrf
def student_register():
    if "student" in session:
        return redirect(url_for("main.home"))
    if "admin" in session:
        return redirect(url_for("main.admin_dashboard"))

    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        name = request.form.get("name", "").strip()
        department = request.form.get("department", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        graduation_year = request.form.get("graduation_year", "").strip()
        password = request.form.get("password", "")

        if not all([student_id, name, department, password, email, graduation_year]):
            flash("All fields are required.")
            return redirect(url_for("auth.student_register"))

        if not AllowedStudent.query.filter_by(student_id=student_id).first():
            flash(
                "This Student ID is not authorized to register. Please contact the admin if this is a mistake."
            )
            return redirect(url_for("auth.student_register"))

        if Student.query.filter_by(student_id=student_id).first():
            flash("This Student ID is already registered. Please login.")
            return redirect(url_for("auth.student_login"))

        if Student.query.filter_by(email=email).first():
            flash("This email address is already in use. Please use a different one or login.")
            return redirect(url_for("auth.student_login"))

        if not valid_password(password):
            flash("Password must be at least 10 characters and include letters and numbers.")
            return redirect(url_for("auth.student_register"))

        # Auto-verify accounts on registration (no email verification required)
        new_student = Student(
            student_id=student_id,
            name=name,
            department=department,
            password=generate_password_hash(password),
            email=email,
            phone=phone,
            graduation_year=int(graduation_year) if graduation_year.isdigit() else None,
            is_verified=True,
        )
        db.session.add(new_student)
        db.session.commit()

        flash("Registration successful! You can now log in.")
        return redirect(url_for("auth.student_login"))

    return render_template("student_register.html", departments=DEPARTMENTS)

@auth_bp.route("/student/forgot-password", methods=["GET", "POST"])
@require_csrf
def forgot_password():
    if request.method == "POST":
        if password_reset_is_rate_limited():
            flash("Too many password reset requests. Please wait an hour and try again.")
            return redirect(url_for("auth.forgot_password"))

        email = request.form.get("email", "").strip().lower()
        student = Student.query.filter_by(email=email).first()
        if student:
            token = password_reset_serializer.dumps(student.email, salt="student-password-reset")
            reset_url = public_url_for("auth.reset_password", token=token)

            try:
                current_app.extensions["mail"].send_message(
                    subject="AU Daily Password Reset",
                    recipients=[student.email],
                    html=render_template(
                        "password_reset_email.html", name=student.name, reset_url=reset_url
                    ),
                )
            except Exception:
                current_app.logger.exception("Unable to send password-reset email")

        flash("If an account matches that email, a password reset link has been sent.")

        return redirect(url_for("auth.student_login"))

    return render_template("forgot_password.html")


@auth_bp.route("/student/reset-password/<token>", methods=["GET", "POST"])
@require_csrf
def reset_password(token):
    try:
        email = password_reset_serializer.loads(token, salt="student-password-reset", max_age=900)
    except Exception:
        flash("The password reset link is invalid or has expired.", "warning")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not valid_password(password):
            flash("Password must be at least 10 characters and include letters and numbers.")
            return redirect(url_for("auth.reset_password", token=token))
        if password != confirm_password:
            flash("The passwords do not match.", "warning")
            return redirect(url_for("auth.reset_password", token=token))

        student = Student.query.filter_by(email=email).first()
        if student:
            student.password = generate_password_hash(password)
            db.session.commit()
            flash("Your password has been updated. You can now sign in.")
            return redirect(url_for("auth.student_login"))

    return render_template("reset_password.html", token=token)


@auth_bp.route("/student/request-admin-recovery", methods=["GET", "POST"])
@require_csrf
def request_admin_recovery():
    if request.method == "POST":
        if password_reset_is_rate_limited():
            flash("Too many recovery requests. Please wait an hour and try again.")
            return redirect(url_for("auth.request_admin_recovery"))

        student_id = request.form.get("student_id", "").strip()
        recovery_email = request.form.get("recovery_email", "").strip()
        contact_note = request.form.get("contact_note", "").strip()

        if not student_id or not recovery_email:
            flash("Student ID and a recovery email address are required.", "warning")
            return redirect(url_for("auth.request_admin_recovery"))

        student = Student.query.filter_by(student_id=student_id).first()
        if not student:
            flash("No registered student account was found for that Student ID.", "warning")
            return redirect(url_for("auth.request_admin_recovery"))

        pending_request = RecoveryRequest.query.filter_by(
            student_id=student_id,
            status="Pending",
        ).first()
        if pending_request:
            pending_request.recovery_email = recovery_email
            pending_request.contact_note = contact_note
            pending_request.created_at = datetime.now()
        else:
            db.session.add(RecoveryRequest(
                student_id=student_id,
                recovery_email=recovery_email,
                contact_note=contact_note,
            ))
        create_admin_notification(
            "recovery",
            f"New account recovery request from student {student_id}.",
            "main.admin_recovery_requests",
        )
        db.session.commit()
        try:
            send_admin_alert(
                "AU Daily: new account recovery request",
                "New account recovery request",
                {
                    "Student ID": student_id,
                    "Recovery email": recovery_email,
                    "Contact note": contact_note or "Not provided",
                },
            )
        except Exception:
            current_app.logger.exception("Unable to send admin recovery alert email")
        flash(
            "Your recovery request has been sent. Contact the administrator to verify your identity."
        )
        return redirect(url_for("auth.student_login"))

    return render_template("admin_recovery.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
@require_csrf
def logout():
    if request.method == "GET":
        # For GET requests, log the user out and redirect gracefully.
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("main.home"))

    # For POST requests, which is the standard secure method.
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("main.home"))
