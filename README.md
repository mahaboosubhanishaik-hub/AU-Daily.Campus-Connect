# AU Daily - Campus Connect

AU Daily is a secure, scalable web application designed to streamline communication and resource sharing within a university campus. It provides distinct portals for students and administrators, with a robust authentication system to ensure that only authorized individuals can access the platform.

## Key Features

- **Role-Based Access Control**: Separate login and registration systems for students and administrators.
- **Whitelisted Student Registration**: Only students whose registration numbers are pre-approved by an admin (via the `allowed_students.csv` file) can create an account.
- **Secure Authentication**:
  - Passwords are securely hashed and salted using `werkzeug.security`.
  - Protection against Cross-Site Request Forgery (CSRF) on all forms.
  - Rate limiting on login and password reset attempts to prevent brute-force attacks.
- **Email Verification**: New student accounts must be verified via a unique link sent to their email, ensuring the validity of the provided email address.
- **Account Recovery**:
  - **Self-Service Password Reset**: Students can request a password reset link to their verified email.
  - **Admin-Assisted Recovery**: For cases where email is inaccessible, students can submit a recovery request that notifies administrators to manually verify and assist.
- **Administrator Dashboard**: A central place for administrators to manage the application, including viewing recovery requests and other administrative tasks.
- **Database Management Scripts**:
  - `reset_db.py`: A destructive script for development to completely reset the database, create an initial admin, and load the initial list of allowed students.
  - `update_allowed_ids.py`: A non-destructive script to add new students from the CSV file to the database without affecting existing data.

---

## Project Structure

```
auEapp/
├── app.py                  # Main Flask application file, configuration, and routes.
├── auth.py                 # Handles all authentication logic (login, register, logout, recovery).
├── models.py               # Defines the database schema (Student, Admin, etc.).
├── reset_db.py             # [DEV-ONLY] Destructive script to reset the database.
├── update_allowed_ids.py   # Safely adds new student IDs to the authorization list.
├── allowed_students.csv    # Whitelist of student registration numbers allowed to sign up.
├── requirements.txt        # Python package dependencies.
├── .env                    # Environment variables (DATABASE_URL, SECRET_KEY, etc.).
├── static/                 # CSS, JavaScript, and image files.
└── templates/              # HTML templates for the user interface.
```

---

## Setup and Installation

Follow these steps to set up the project for development.

### 1. Prerequisites

- Python 3.8+
- A MySQL-compatible database server.

### 2. Clone the Repository

```bash
git clone <your-repository-url>
cd auEapp
```

### 3. Set up a Virtual Environment

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

Create a file named `.env` in the root directory (`auEapp/`) and add the following configuration. **Do not commit this file to version control.**

```ini
# Flask Configuration
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY='a_very_long_and_random_secret_key_here'

# Database URL
DATABASE_URL='mysql+pymysql://<user>:<password>@<host>/<database_name>'

# Email Configuration (e.g., for Gmail)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME='your-email@gmail.com'
MAIL_PASSWORD='your-app-password' # Use an App Password for security

# Admin Configuration (for reset_db.py and alerts)
INITIAL_ADMIN_ID='admin'
INITIAL_ADMIN_PASSWORD='a_very_strong_initial_password'
ADMIN_EMAIL_ALERTS='admin-alert-recipient@example.com'
```

### 6. Prepare the Student Whitelist

Create a file named `allowed_students.csv` in the root directory. Add the registration numbers of students who are authorized to create an account, one per line.

```csv
324207360001
324207360002
324207360003
```

---

## Database Initialization

You have two scripts to manage the database.

### First-Time Setup (Destructive)

This script will **delete all existing data** and create the tables from scratch. It also creates the initial admin user specified in your `.env` file.

```bash
python reset_db.py
```

### Adding New Students (Non-Destructive)

To authorize new students without losing any data, add their IDs to `allowed_students.csv` and run:

```bash
python update_allowed_ids.py
```

---

## Running the Application

Once the setup is complete, run the Flask development server:

```bash
flask run
```

The application will be available at `http://127.0.0.1:5000`.