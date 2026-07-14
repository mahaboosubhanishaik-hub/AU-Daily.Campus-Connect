from flask import Flask
from flask_mail import Mail, Message
from dotenv import load_dotenv
import os
import sys

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(env_path, override=True)

app = Flask(__name__)

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME', 'noreply@audaily.com')

if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
    print("Error: MAIL_USERNAME or MAIL_PASSWORD not found in .env file.")
    sys.exit(1)

mail = Mail(app)

with app.app_context():
    print("Attempting to send a test email...")
    try:
        # Sending the test email to your own address so you can verify it arrives
        msg = Message('Flask-Mail Test', sender=app.config['MAIL_USERNAME'], recipients=[app.config['MAIL_USERNAME']])
        msg.body = "This is a test email sent from the Flask application. If you received this, your email configuration is working perfectly!"
        mail.send(msg)
        print(f"Test email sent successfully to {app.config['MAIL_USERNAME']}!")
    except Exception as e:
        print(f"Failed to send email. Error: {e}")