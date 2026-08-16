# AU Daily - Technical Documentation

Welcome to the AU Daily developer documentation. This file is designed to be fully editable so you can keep it updated as your project grows.

## 1. Project Overview
AU Daily is a comprehensive Flask-based social and utility platform tailored for Andhra University students. It bridges the gap between campus administration and students while providing utility tools like GPA calculators, and planners.

## 2. Tech Stack
- **Backend:** Python, Flask
- **Database:** MySQL, SQLAlchemy (ORM), Flask-Migrate (Alembic)
- **Frontend:** HTML5, CSS3 (Bootstrap), Jinja2 Templating

## 3. Database Models (Core Schema)
Here are the core database tables that power the application:
- **Authentication & Users:** `Admin`, `Student`, `AllowedStudent`
- **Social & Interactions:** `Follower`, `PrivateMessage`, `Feedback`
- **Campus Events:** `Event`, `EventLike`, `Comment`, `EventRegistration`
- **Campus News Feed:** `NewsPost`, `NewsLike`, `NewsComment` 
- **Campus Utilities:** `LostItem`, `AnonymousDoubt`, `DoubtReply`, `Poll`, `PollOption`, `PollVote` 
- **Peer Learning:** `StudentSkill`, `SkillEndorsement`
- **Productivity & Academics:** `Task`, `Resource`, `ResourceComment` 
- **Media & AI:** Gallery

## 4. Key Files & Directories
- `app.py`: The heart of the application containing all backend routes, logic, and database models.
- `reset_db.py`: A utility script used to drop and recreate the database schema and populate allowed students. **(Do not run in production)**
- `update_allowed_ids.py`: Script to append new valid student registration IDs without dropping the database.
- `allowed_students.csv`: The whitelist of student IDs permitted to register.
- `.env`: Environment variables configuration file (DO NOT COMMIT to Git).
- `static/`: Contains static assets like images, CSS, and user-uploaded media (`static/media/`).
- `templates/`: Contains all HTML files structured with Jinja2 (`{% %}`) templating.

## 5. Adding a New Feature (Quick Guide)
To add a new page to the application, follow these general steps:

1. **Create the Route (in `app.py`):**
   ```python
   @app.route('/new_feature')
   def new_feature():
       if 'student' not in session:
           return redirect(url_for('student_login'))
       return render_template("new_feature.html")
   ```
2. **Create the Template (in `templates/new_feature.html`):**
   ```html
   {% extends "base.html" %}
   {% block content %}
       <h2>My New Feature</h2>
       <p>Content goes here...</p>
   {% endblock %}
   ```
3. **Add to Navigation:** Update `templates/base.html` or the sidebar to include a link to `{{ url_for('new_feature') }}`.

## 6. Environment Variables (`.env`)
Ensure the following keys are maintained in your `.env` file for the app to function securely:
- `SECRET_KEY`: Secures the Flask session and password reset tokens.
- `DATABASE_URL`: Connection string for the MySQL server.

## 7. Future Enhancements (TODOs)
*Use this section to track what you want to build next.*
- [x] Add email verification upon student registration.
- [x] Implement pagination for the campus events page.

## 8. Recent Completion Notes
- Added the Skill Exchange Hub for searching student skills, filtering by department, endorsing skills, and connecting with skilled peers.
- Improved Lost & Found reporting with required-field validation, CSRF protection, clearer upload failures, and a wider search input with an icon.
- Clarified administrator password-recovery status so new requests show as Pending until the admin verifies identity and generates a temporary password.
