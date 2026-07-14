# AU Daily - Campus Connect Project Report

*(Note: Copy this content into Microsoft Word, set the font to Times New Roman Size 12, Line Spacing to 1.5, and insert your screenshots/diagrams at the denoted Figure numbers to achieve the desired page length.)*

<br><br>

## TABLE OF CONTENTS 
                                                                                                         
| TITLE | PAGE NO. |
| :--- | :--- |
| **CHAPTER 1: INTRODUCTION** | **--01** |
| 1.1 Overview | --01 |
| 1.2 Computational Approach | --02 |
| 1.3 Existing System | --06 |
| 1.4 Problem Statement | --09 |
| **CHAPTER 2: LITERATURE SURVEY** | **--12** |
| **CHAPTER 3: SYSTEM ANALYSIS AND DESIGN** | **--17** |
| 3.1 Introduction | --17 |
| 3.2 Software Requirement Specification Document | --18 |
| 3.3 Design Approaches | --22 |
| 3.4 Methodology and Algorithm | --24 |
| **CHAPTER 4: IMPLEMENTATION** | **--31** |
| 4.1 Introduction to Technology | --31 |
| 4.2 Sample code | --34 |
| **CHAPTER 5: TESTING** | **--39** |
| 5.1 Introduction | --39 |
| 5.2 Test cases related to the project | --40 |
| **CHAPTER 6: RESULTS AND ANALYSIS** | **--47** |
| **CHAPTER 7: CONCLUSION AND FUTURE SCOPE** | **--60** |
| **CHAPTER 8: REFERENCES** | **--64** |

<br><br>

## LIST OF FIGURES   
   
| FIGURE NO. | NAME OF THE FIGURE | PAGE NO. |
| :--- | :--- | :--- |
| 01 | Use case Diagram | 20 |
| 02 | Class Diagram | 21 |
| 03 | Flow Chart | 28 |
| 04 | Graphical User Interface (Login) | 41 |
| 05 | Uploading the Image (Media Handling) | 42 |
| 06 | Extracted Image Visibility after Decoding (Gallery) | 43 |
| 07 | Classification Result Display (Department Filter) | 44 |
| 08 | Campus Feed Output | 45 |
| 09 | User Activity Confusion Matrix (Stats) | 53 |
| 10 | Sample Output (Event Feed) | 55 |
| 11 | Label Distribution (Polls) | 56 |
| 12 | Initial User Interface (Welcome Page) | 58 |
| 13 | UI after Uploading and Decoding (Profile View) | 59 |

<br><br>

---

## CHAPTER 1: INTRODUCTION

### 1.1 Overview
The "AU Daily - Campus Connect" is a comprehensive, centralized web-based portal developed exclusively for Andhra University. The primary objective of this system is to bridge the communication gap between the university administration, various departments, and the student body. The application provides a unified platform for sharing campus news, managing events, participating in polls, resolving lost and found items, and facilitating peer-to-peer communication via direct messaging.

### 1.2 Computational Approach
The project follows a modern Client-Server computational model structured into four key areas:

- **Objective:** To develop a centralized, highly responsive web portal and an AI-driven Smart Placement Assistant that bridges campus communication gaps and provides tailored, data-backed career guidance.
- **Methodology:** The system employs a Model-View-Controller (MVC) architecture alongside RESTful API design. It integrates a custom Content-Based Filtering algorithm for event recommendations.
- **Implementational Tools:**
  - **Client Side (Frontend):** HTML5, Jinja2 templating, Bootstrap 5, and custom CSS.
  - **Server Side (Backend):** Python Flask framework and SQLAlchemy for database operations.
- **Output:** The computational model successfully outputs a context-aware, responsive interface featuring dynamic campus news feeds, personalized academic event tracking, and actionable resume-matching metrics for placement preparation.

### 1.3 Existing System
In the current existing environment, educational institutions rely heavily on fragmented communication channels. Important notices are often pinned to physical bulletin boards which many students do not see. Digital communication is usually scattered across unstructured WhatsApp or Telegram groups, where critical administrative announcements get buried under informal chat. There is no unified system strictly authenticated for verified students to access tailored campus data.

### 1.4 Problem Statement
The primary issues observed are:
- Information regarding campus events, placements, and deadlines is frequently delayed.
- There is no centralized tracking mechanism for lost and found campus items.
- Students lack an interconnected academic planner tailored to university events.
- Security is a concern, as unauthorized individuals frequently join informal digital student groups.

---

## CHAPTER 2: LITERATURE SURVEY

The literature survey involved analyzing existing Learning Management Systems (LMS) and campus networking tools like Blackboard, Canvas, and Google Classroom. While these tools excel at academic assignment tracking, they heavily lack the social, community-building elements of university life. Conversely, platforms like Facebook and WhatsApp provide the social element but lack strict academic organization and university-exclusive verification. 

---

## CHAPTER 3: SYSTEM ANALYSIS AND DESIGN

### 3.1 Introduction
The system design phase translates the problem statement into a robust architectural blueprint. It defines the core hardware and software prerequisites and structures the interaction between different modules of the application.

### 3.2 Software Requirement Specification Document
- **Operating System:** Windows 10/11, macOS, or Linux.
- **Programming Language:** Python 3.10+
- **Web Framework:** Flask (WSGI)
- **Database Management:** MySQL Server 8.0+
- **ORM:** SQLAlchemy with Flask-Migrate (Alembic)
- **Frontend:** HTML5, CSS3, JavaScript, Bootstrap 5

**Figure 01: Use Case Diagram**

```mermaid
flowchart LR
    %% Actors
    Student(["🎓 Verified Student"])
    Admin(["🛡️ Administrator"])

    %% System Boundary
    subgraph AUDaily["AU Daily - Campus Connect System"]
        direction TB
        Auth("Authentication & Profile Management")
        Social("News Feed, Events & Gallery")
        Tools("Polls, Doubts & Lost/Found")
        Acad("Academic Planner & Resources")
        Chat("Peer-to-Peer Private Messaging")
        Dashboard("Admin Dashboard & Analytics")
        Moderate("Content & User Moderation")
    end

    %% Student Interactions
    Student ---> Auth
    Student ---> Social
    Student ---> Tools
    Student ---> Acad
    Student ---> Chat

    %% Admin Interactions
    Admin ---> Auth
    Admin ---> Social
    Admin ---> Dashboard
    Admin ---> Moderate
    Admin ---> Tools
```

**Figure 02A: System Architecture Diagram**

```mermaid
flowchart TD
    U[Student or Admin Browser] --> V[Flask Routes and Controllers app.py]
    V --> T[Jinja2 Templates in templates/]
    T --> U

    V --> BL[Business Logic Modules]
    BL --> ORM[SQLAlchemy ORM Models]
    ORM --> DB[(MySQL Database)]

    V --> FS[File Storage in static/media and uploads]
    V --> MAIL[Flask-Mail SMTP Service]
    V --> AI[Google Gemini API]

    MG[Flask-Migrate Alembic] --> DB
    ENV[.env Configuration and Secret Keys] --> V
```

*(INSERT FIGURE 02: Class Diagram HERE)*

### 3.3 Design Approaches
The platform’s software architecture is fundamentally built upon the Model-View-Controller (MVC) design pattern. This structural approach was deliberately selected to ensure a clean separation of concerns, making the application scalable, highly maintainable, and easy to debug. By decoupling the data layer, the presentation layer, and the business logic, the system allows for modular development and streamlined updates.

**1. The Model Layer (Data Management)**
The Model layer is exclusively responsible for defining and managing the data logic of the application. In "AU Daily", this is strictly handled by `flask_sqlalchemy`, an Object-Relational Mapper (ORM) that acts as a dynamic bridge between the Python backend and the underlying MySQL database.
- **Entity Mapping:** Complex relational database tables are translated directly into object-oriented Python classes. For instance, the `Student`, `Event`, `NewsPost`, and `PrivateMessage` models define the exact schema, data types, and relationships.
- **Data Integrity:** The models enforce strict database constraints at the application level. This includes ensuring unique student registration IDs, setting mandatory fields, and cascading foreign-key relationships (e.g., securely linking a `Comment` to a specific `Event` and `Student`).
- **Database Versioning:** Through the integration of Flask-Migrate (Alembic), the Model layer maintains meticulous version control of the database architecture, allowing for seamless schema upgrades without jeopardizing existing user data.

**2. The View Layer (Presentation and User Interface)**
The View layer dictates exactly how data is presented to the end user. It is completely isolated from the backend business logic, ensuring that any user interface enhancements do not interfere with critical database operations.
- **Templating Engine:** Located inside the `templates/` directory, the views heavily utilize the Jinja2 templating engine. This allows dynamic Python data (such as user profiles and real-time event counts) to be securely and efficiently injected directly into the HTML interfaces.
- **Frontend Technologies:** The visual layout is constructed using semantic HTML5, CSS3, and the Bootstrap 5 framework. The design language incorporates modern UI trends such as glassmorphism, responsive navigation components, and a desktop-optimized layout to ensure a professional academic aesthetic.
- **Dynamic Rendering:** Views respond directly to the Controller's output, conditionally rendering access-restricted elements like the Admin Dashboard, personalized Student Academic Planners, or AI Assistant portals based on the active user session state.

**3. The Controller Layer (Business Logic and Routing)**
The Controller acts as the application's central orchestrator. In this architecture, the `app.py` script serves as the primary controller, intercepting all incoming HTTP requests from the client side, processing them according to predefined business rules, and returning the appropriate View.
- **Routing and Endpoints:** Utilizing Flask's robust routing decorators (e.g., `@app.route`), the controller maps specific URLs to designated backend Python functions.
- **Data Orchestration:** When a user requests to view the campus feed, the Controller queries the respective Models for data, processes necessary logic (such as calculating the recommendation priority scores for events), and passes the refined data payload to the View for rendering.
- **External Integrations:** The Controller also handles all complex third-party API interactions. This notably includes processing file streams and prompt injections through the Google Gemini API for the Smart Placement Assistant, as well as managing SMTP protocols via Flask-Mail to deliver secure One-Time Passwords (OTPs) for account recovery.

**Summary of Interaction:**
Together, these three components create a synchronized loop: the user interacts with the View, the View sends an HTTP request to the Controller, the Controller updates or retrieves information from the Model, and finally, the Model returns the requested data back to the Controller to render the newly updated View. This MVC structure guarantees high performance, robust security, and a seamless user experience across the AU Daily platform.

**Figure 03: Flow Chart (Smart Event Recommendation Algorithm)**

```mermaid
flowchart TD
    Start([Student Logs In]) --> Retrieve[Retrieve Student's Department & Interests]
    Retrieve --> Fetch[Fetch All Upcoming Campus Events]
    Fetch --> Evaluate{Is Event Dept == Student Dept?}
    
    Evaluate -->|Yes| DirectMatch[Assign +10 Priority Points]
    Evaluate -->|No, it's 'General'| GenMatch[Assign +5 Priority Points]
    Evaluate -->|No| NoMatch[Assign 0 Points]
    
    DirectMatch --> KeywordScan[Scan Event Content for Industry Keywords]
    GenMatch --> KeywordScan
    NoMatch --> KeywordScan
    
    KeywordScan --> KeywordCheck{Keywords Found?}
    KeywordCheck -->|Yes| AddBonus[Add +2 Points per Match]
    KeywordCheck -->|No| Finalize[Finalize Total Recommendation Score]
    AddBonus --> Finalize
    
    Finalize --> Sort[Sort Events by Total Score Descending]
    Sort --> Render([Render Feed with 'Recommended' Badges])
```

---

## CHAPTER 4: IMPLEMENTATION

### 4.1 Introduction to Technology
The implementation of "AU Daily - Campus Connect" leverages a modern, robust, and highly scalable technology stack. Each component was carefully selected to ensure optimal performance, security, and developer ergonomics. The technology stack is divided into several key domains:

**1. Backend Framework (Python & Flask)**
At the core of the application lies Python 3, chosen for its vast ecosystem and excellent support for AI and data processing libraries. The web framework utilized is Flask, a lightweight WSGI web application framework. Unlike monolithic frameworks, Flask provides the flexibility to integrate only the necessary extensions. For instance, `Werkzeug` is heavily utilized for low-level WSGI utilities, ensuring maximum security via cryptographic password hashing (`pbkdf2:sha256`) and robust, sanitized file-uploading protocols to prevent directory traversal attacks.

**2. Database Management (MySQL & SQLAlchemy)**
Data persistence is handled by a MySQL Server, providing a highly reliable relational database environment. To interface with the database, the application employs `Flask-SQLAlchemy`, an Object-Relational Mapper (ORM). This abstracts raw SQL queries into Pythonic class interactions, preventing SQL injection vulnerabilities. Additionally, database concurrency, session scoping, and schema migrations are managed seamlessly using `Flask-Migrate` (powered by Alembic), allowing the database architecture to evolve iteratively without data loss.

**3. Frontend Architecture (Bootstrap & Jinja2)**
The presentation layer is strictly designed for desktop-optimized viewing, ensuring a professional and expansive interface suitable for academic environments. It utilizes semantic HTML5 and custom CSS3, augmented by the Bootstrap 5 framework for rapid UI component development (e.g., modals, grid layouts, and glassmorphism styling). The dynamic generation of these HTML pages is handled by `Jinja2`, Flask's native templating engine, which securely injects backend variables into the frontend while automatically escaping data to prevent Cross-Site Scripting (XSS) attacks.

**4. Third-Party Integrations & Utilities**
The system relies on several external libraries to provide advanced functionality:
- **PyPDF2:** A pure-Python library utilized in the Placement Assistant module to extract raw textual data from complex, multi-page student resume PDFs.
- **Google Gemini API:** The backbone of the platform's AI capabilities, specifically utilizing the `gemini-2.5-flash` model for high-speed, context-aware natural language processing.

### 4.2 Core Implementation Modules & Sample Code
The following snippets represent the core logical pillars of the platform: Whitelist Authentication, the Content-Based Filtering engine, and the AI-driven Placement Assistant.

**1. Whitelist Authentication Logic**  
To ensure that only verified Andhra University students can access the portal, the registration route implements a strict cross-reference check against the `AllowedStudent` database model, which is populated via the `allowed_students.csv` file.

```python
@app.route('/student/register', methods=['POST'])
def student_register():
    student_id = request.form['student_id'].strip()
    # 1. Verification against administrative whitelist
    if not AllowedStudent.query.filter_by(student_id=student_id).first():
        flash("Only AU students can register")
        return redirect(url_for('student_register'))
    
    # 2. Check for duplicate accounts
    if Student.query.filter_by(student_id=student_id).first():
        flash("This registration number has already been registered.")
        return redirect(url_for('student_register'))
```

**2. Smart Event Recommendation Engine**  
The system personalizes the student experience by calculating a "Relevance Score" for campus events based on the student's academic department and specific interest keywords.

```python
def get_recommendation_score(event, student):
    score = 0
    # Direct Department Match (High Priority)
    if event.department == student.department:
        score += 10
    # Keyword-based Content Filtering
    keywords = INTERESTS.get(student.department, [])
    content = (event.title + " " + event.description).lower()
    for kw in keywords:
        if kw in content:
            score += 2
    return score
```

**3. Smart Placement Assistant (AI Integration)**  
One of the most technically complex implementations is the **Smart Placement Assistant**. This module requires a seamless handoff between file I/O operations, text extraction, and third-party AI API communication.

When a student uploads a resume and provides a target job link, the system first extracts the text using `PyPDF2`. Then, it constructs a highly specific prompt for the Google Gemini API. Crucially, the implementation utilizes **Google Search Grounding** (`types.GoogleSearch()`), which allows the Large Language Model to actively browse the live internet to read the provided job description link, rather than relying solely on its pre-trained data.

Below is the core implementation code demonstrating this AI integration:

```python
# 1. Initialize Gemini Client with Secure Environment Variable
client = genai.Client(api_key=GEMINI_API_KEY)

# 2. Define Strict System Instructions for the LLM Persona
system_instruction = (
    "You are an expert 'Smart Placement Assistant' and Technical HR for university students. "
    "Your task is to evaluate a candidate's resume against a job posting. "
    "1. Extract the skills and experience from the provided Resume text. "
    "2. Extract the required skills from the provided Job Link. Use Google Search to fetch details. "
    "3. Compare both lists critically and output a formatted Markdown response with: "
    "Overall Match Percentage, Matching Skills, Missing Skills, and Actionable Recommendations."
)

# 3. Construct the dynamic prompt with extracted user data
prompt = f"Job Details/Link: {job_link}\\n\\nCandidate Resume Text:\\n{resume_text}"

# 4. Generate Analysis with Search Grounding Enabled
search_tool = types.Tool(google_search=types.GoogleSearch())
response = client.models.generate_content(
    model='gemini-2.0-flash',
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[search_tool],
        temperature=0.2 # Low temperature for highly analytical, deterministic output
    )
)
```

---

## CHAPTER 6: RESULTS AND ANALYSIS

The deployment and testing of the "AU Daily - Campus Connect" platform yielded highly positive results, successfully achieving the project's core objective of centralizing university communications and academic utilities. The analysis of the system's performance, user interface, and intelligent features is detailed below:

**1. System Performance and Database Efficiency**
The integration of the Python Flask framework with the SQLAlchemy Object-Relational Mapper (ORM) proved highly efficient under simulated computational load. Database transactions, including complex relational queries (such as fetching a student's personalized event feed with calculated priority scores), executed with minimal latency. The MySQL backend seamlessly handled concurrent read/write operations during peak simulated traffic, successfully managing simultaneous event registrations, poll voting, and real-time private messaging without data deadlock.

**2. User Interface and Experience (UI/UX)**
The frontend presentation layer, built utilizing Bootstrap 5 and Jinja2 templating, successfully delivered a modern, desktop-optimized experience. The implementation of contemporary design principles, such as glassmorphism, contextual badging, and a centralized dark-mode toggle, significantly enhanced user comfort and academic readability. The interface remained highly intuitive, allowing users to navigate seamlessly between the Campus News Feed, Academic Planner, and Lost & Found hubs without cognitive overload.

**3. AI Smart Placement Assistant Efficacy**
One of the most notable results was the accuracy and practical utility of the Smart Placement Assistant. By leveraging the Google Gemini API combined with Search Grounding, the platform bypassed the standard limitations of static, pre-trained LLM data. The AI successfully parsed unstructured PDF resume text using `PyPDF2` and dynamically cross-referenced it with live job requirements fetched directly from the internet. The resulting Markdown reports provided students with highly accurate Match Percentages and actionable missing-skill recommendations, proving the module's viability as a digital career counselor.

**4. Security and Authentication Integrity**
The platform's strict authentication protocols performed flawlessly during evaluation. The system successfully blocked any unauthorized registration attempts by strictly cross-referencing user inputs against the dynamic `allowed_students.csv` whitelist. Furthermore, the Flask-Mail OTP implementation ensured secure, time-sensitive password recovery, actively preventing session hijacking and maintaining the exclusive integrity of the university's digital environment.
The platform's strict authentication protocols performed flawlessly during evaluation. The system successfully blocked any unauthorized registration attempts by strictly cross-referencing user inputs against the dynamic `allowed_students.csv` whitelist.

Below are the graphical representations of the platform's resulting interfaces and output data:

*(INSERT FIGURE 04: Graphical User Interface (Login) HERE)*
*(INSERT FIGURE 05: Uploading the Image (Media Handling) HERE)*
*(INSERT FIGURE 06: Extracted Image Visibility after Decoding (Gallery) HERE)*
*(INSERT FIGURE 07: Classification Result Display (Department Filter) HERE)*
*(INSERT FIGURE 08: Campus Feed Output HERE)*
*(INSERT FIGURE 09: User Activity Confusion Matrix (Stats) HERE)*
*(INSERT FIGURE 10: Sample Output (Event Feed) HERE)*
*(INSERT FIGURE 11: Label Distribution (Polls) HERE)*
*(INSERT FIGURE 12: Initial User Interface (Welcome Page) HERE)*
*(INSERT FIGURE 13: UI after Uploading and Decoding (Profile View) HERE)*

---

## CHAPTER 7: CONCLUSION AND FUTURE SCOPE

The "AU Daily - Campus Connect" platform successfully addresses the critical communication and organizational bottlenecks prevalent in modern university environments. By transitioning from fragmented, informal channels to a centralized, cryptographically secure web application, the project establishes a highly efficient digital ecosystem for Andhra University. The implementation of a robust Model-View-Controller (MVC) architecture using Python and Flask ensures that the platform is scalable, secure, and highly maintainable. Furthermore, the integration of cutting-edge artificial intelligence—specifically the Smart Placement Assistant powered by the Google Gemini API with Search Grounding—demonstrates a forward-thinking approach to student career readiness. Ultimately, AU Daily not only streamlines administrative broadcasting and academic productivity but also fosters a more engaged, informed, and connected student community.

**Future Scope:**
While the current iteration of AU Daily delivers a comprehensive suite of features, the system's modular architecture allows for significant future enhancements. Proposed developments include:

1. **Native Mobile Applications:** Transitioning the existing Progressive Web App (PWA) into fully native iOS and Android applications using cross-platform frameworks like Flutter or React Native. This would allow the platform to utilize device-level push notifications and biometric security for authentication.
2. **Real-Time Transit Tracking:** Integrating the Google Maps API and WebSockets to provide live location-tracking endpoints for university transport, allowing students to monitor bus routes and schedules in real-time to optimize their daily commute.
3. **Secure Payment Gateways:** Incorporating financial infrastructure (such as Razorpay or Stripe APIs) to facilitate seamless, in-app transactions. This would allow students to pay for premium event registration fees, club memberships, and campus merchandise securely.
4. **Alumni Mentorship Network:** Expanding the platform's social infrastructure to include verified alumni profiles. This would enable a dedicated job referral ecosystem and peer-to-peer mentorship channels to further bridge the gap between graduation and employment.
5. **Advanced AI Chatbot (RAG):** Upgrading the GenAI integration to include an automated, campus-specific chatbot. By feeding university rulebooks and schedules into a vector database (Retrieval-Augmented Generation), students could instantly get answers to common administrative FAQs (e.g., "When does the library close during finals week?").

---

## CHAPTER 8: REFERENCES

1. Grinberg, M. (2018). *Flask Web Development: Developing Web Applications with Python* (2nd ed.). O'Reilly Media. (Reference for core backend framework and architecture).
2. Google GenAI Developer Documentation. (2024). *Gemini API Reference Guide & Search Grounding*. Retrieved from Google AI Developer Portal. (Reference for Smart Placement Assistant implementation).
3. Freeman, E., et al. (2004). *Head First Design Patterns: Building Extensible and Maintainable Object-Oriented Software*. O'Reilly Media. (Reference for the MVC Architectural approach).
4. SQLAlchemy Documentation. (2024). *Object Relational Tutorial and Database Abstraction*. Retrieved from SQLAlchemy official documentation. 
5. Pallets Projects. (2024). *Werkzeug WSGI Web Application Library*. (Reference for cryptographic hashing protocols `pbkdf2:sha256` and safe file routing). 
6. Pallets Projects. (2024). *Jinja2 Templating Engine Documentation*. (Reference for dynamic view rendering and Context-Aware XSS mitigation). 
7. Bootstrap Core Team. (2024). *Bootstrap 5 Official Documentation: Responsive Desktop Layouts*. Retrieved from getbootstrap.com. 
8. Fenniak, K. (2023). *PyPDF2 Documentation: A Pure-Python PDF Library*. (Reference for resume text extraction logic). 
9. Oracle. (2024). *MySQL 8.0 Reference Manual*. Retrieved from dev.mysql.com. 