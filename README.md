# Library Management System

A web-based Library Management System built with Python and Streamlit, using PostgreSQL on Neon for persistent data storage. The application helps manage library books and related records through a simple, user-friendly interface.

## Features

- **User Authentication:** Email-based login and OTP verification.
- **Email Configuration:** Gmail SMTP integration for sending verification emails.
- **Book Management:** Maintain a catalogue of library books.
- **Database Integration:** Store and manage data using Neon PostgreSQL.
- **Issue Management:** Maintain records of issued books.
- **Borrow Requests:** Support book borrowing request management.
- **Cloud Deployment:** Deploy the application using Streamlit Community Cloud.

## Tech Stack

| Technology | Purpose |
|---|---|
| Python | Application logic |
| Streamlit | Web interface |
| SQLAlchemy | Database connectivity and SQL operations |
| PostgreSQL | Relational database |
| Neon | Cloud-hosted PostgreSQL database |
| Gmail SMTP | Email delivery |
| Pandas | Data handling |

## Project Structure

```text
Library-Management-System/
│
├── library_app.py       # Main Streamlit application
├── requirements.txt     # Python dependencies
├── README.md            # Project documentation
└── .gitignore           # Files excluded from Git
```

## Installation and Setup

### 1. Clone the Repository

```bash
git clone YOUR_REPOSITORY_URL
cd Library-Management-System
```

Replace `YOUR_REPOSITORY_URL` with your GitHub repository URL.

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Secrets

Create a `.streamlit/secrets.toml` file in your project directory.

```toml
[connections.neon]
url = "YOUR_NEON_DATABASE_URL"

[email]
sender = "YOUR_GMAIL_ADDRESS"
app_password = "YOUR_GMAIL_APP_PASSWORD"

[auth]
allowed_emails = ["YOUR_AUTHORIZED_EMAIL"]
```

Replace the placeholders with your actual configuration values. Use a Gmail App Password where required.

**Security:** Never commit your `secrets.toml` file, database credentials, or email passwords to GitHub.

### 5. Run the Application

```bash
streamlit run library_app.py
```

The application will open in your browser.

## Database

The application uses Neon PostgreSQL to store persistent library data.

Database records include tables for:

- Books
- Users
- Issued books
- Borrow requests

The application connects to the database using SQLAlchemy and the PostgreSQL driver.

## Deployment

The application can be deployed using Streamlit Community Cloud.

1. Push the project files to GitHub.
2. Open Streamlit Community Cloud.
3. Create a new app and select your repository.
4. Set the main application file to `library_app.py`.
5. Add the required configuration to the app's **Secrets** settings.
6. Deploy the application.

Make sure `requirements.txt` includes the dependencies required by your application.

## Future Improvements

- Book search and filtering
- Improved dashboard and statistics
- Fine and overdue tracking
- Enhanced user roles and permissions
- Improved borrowing and return workflows

## Author

**Harshad Sontakke**

Built as a Python-based project to explore web application development, database integration, and authentication.

---

*This project uses Streamlit for its interface and Neon PostgreSQL for persistent data storage.*
