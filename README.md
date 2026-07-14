# AU Daily - Campus Connect

AU Daily is a Flask-based web application designed to connect students and administrators within a university campus. It features event management, a campus news feed, student profiles, and an admin dashboard.

## Features

*   **Student Portal**: Login, view events, register for events, like/comment, and manage profile.
*   **Admin Dashboard**: Manage events, view analytics (charts), and oversee student activities.
*   **Campus News**: A social feed for sharing updates and media.
*   **Notifications**: Real-time alerts for new events and reminders. 
*   **Security**: Restricted registration based on an allowed list of Student IDs.

## Prerequisites

*   Python 3.8 or higher
*   MySQL Server

## Installation

1.  **Clone or Download the Repository**
    Navigate to the project folder:
    ```bash
    cd auEapp
    ```

2.  **Create a Virtual Environment** (Recommended)
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Mac/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    bash
    pip install -r requirements.txt
    

## Database Setup

1.  **Configure MySQL**
    *   Make sure your MySQL server is running.
    *   Create a database named `au_daily1` (or match what is in your config).

2.  **Environment Variables**
    Copy `.env.example` to `.env` for local work. On a hosting provider, set the same values in its secret/environment-variable panel; do not upload `.env`.
    
    **Example `.env` file:**
    ```ini
    APP_ENV=production
    SECRET_KEY=your-long-random-secret
    DATABASE_URL=mysql+pymysql://user:password@host/au_daily1
    PUBLIC_BASE_URL=https://your-domain.example
    ADMIN_ALERT_RECIPIENT=admin@your-domain.example

    # For Email (e.g., Gmail)
    MAIL_USERNAME=your_email@gmail.com
    MAIL_PASSWORD=your_gmail_app_password
    ```
    *Replace `root` and `your_password` with your actual MySQL credentials.*

3.  **Setup Allowed Students**
    To control who can register, create a file named `allowed_students.csv` in the project root. List valid Student IDs in the first column.
    
    **Example `allowed_students.csv`:**
    ```csv
    32112345001
    32112345002
    324207360124
    ```

4.  **Initialize the Database**
    For a new, empty production database, set `INITIAL_ADMIN_ID` and `INITIAL_ADMIN_PASSWORD` (12+ characters), then run the safe bootstrap script once. It refuses to run against an existing database.
    ```bash
    python bootstrap_production_db.py
    ```
    `reset_db.py` is destructive and is for local development only.

### Database Migrations (Making Changes to the Database)

After the initial setup, you should **not** run `reset_db.py` again, as it will delete all your data. To make changes to the database structure (e.g., adding a new column to a table), use the following migration commands:

1.  **Make your changes** in the models in `app.py`.

2.  **Generate a migration script**:
    ```bash
    flask --app app db migrate -m "A short description of your changes"
    ```

3.  **Apply the changes** to the database:
    ```bash
    flask --app app db upgrade
    ```

## Managing Allowed Students

To add new student IDs **without resetting the database** (preserving existing users and events):

1.  Update the `allowed_students.csv` file with the new IDs (you can keep or remove old ones, the script handles duplicates).
2.  Run the update script:
    ```bash
    python update_allowed_ids.py
    ```

## Running the Application

1.  Start the Flask server:
    ```bash
    python app.py
    ```

2.  Open your browser and navigate to:
    `http://127.0.0.1:5001`

## Deployment & Updates

### 1. Preparing for Production
Set all values from `.env.example`, especially:
```ini
APP_ENV=production
PUBLIC_BASE_URL=https://your-domain.example
SECRET_KEY=a-long-random-secret
ADMIN_ALERT_RECIPIENT=admin@your-domain.example
```
Terminate HTTPS at your host/reverse proxy and set `TRUST_PROXY_COUNT` to the exact number of trusted proxies (usually `1`). Do not trust forwarded headers otherwise.

Start the application with Gunicorn, not `python app.py`:
```bash
gunicorn --workers 3 --bind 0.0.0.0:8000 app:app
```
The included `Procfile` supports hosts that use it. Configure the host's `PORT` value if required.

Before the first deployment, back up the database. For an existing installation, apply migrations and then move existing resource files out of the public static directory:
```bash
flask --app app db upgrade
python migrate_private_resources.py
```

### 2. How to Update the Live App
If you make changes to the code (e.g., adding a feature or fixing a bug), follow these steps to update your live server:

1.  **Push Changes**: Upload your code changes to your Git repository (GitHub/GitLab).
2.  **Pull on Server**: Log in to your server and pull the latest changes:
    ```bash
    git pull origin main
    ```
3.  **Install Dependencies** (if you added new packages):
    ```bash
    pip install -r requirements.txt
    ```
4.  **Back up, then update the database**:
    ```bash
    flask --app app db upgrade
    ```
5.  **Restart the App**:
    *   If using standard systemd/gunicorn: `sudo systemctl restart au_daily`
    *   If running manually (testing): Stop the script (Ctrl+C) and run `python app.py` again.
