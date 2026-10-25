import base64
import csv
import hashlib
import secrets
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import streamlit as st

# ---------------- Configuration ----------------
st.set_page_config(
    page_title="Library Management System",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DATA_DIR = Path(__file__).parent
BOOKS_FILE = DATA_DIR / "book_data.txt"
USERS_FILE = DATA_DIR / "user_data.txt"
ISSUES_FILE = DATA_DIR / "issue_data.txt"

OTP_TTL = 300
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = 30
STUDENT_DOMAIN = "@vit.edu"

LIB_PAGES = ["Dashboard", "Add Book", "Books", "Register User", "Issue Book", "Return Book", "History"]
STU_PAGES = ["My Dashboard", "Browse Books", "My History"]

# ---------------- Styling ----------------
STYLE = """
<style>
[data-testid="stSidebar"], [data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] {display: none;}
.block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,.25); padding: 1rem; border-radius: 12px;
}
.hero {
    height: 86vh; border-radius: 18px; padding: 2.5rem; color: #fff;
    display: flex; flex-direction: column; justify-content: flex-end;
    background-image: linear-gradient(rgba(10,20,40,.35), rgba(10,20,40,.80)), __BG__;
    background-size: cover; background-position: center;
}
.hero h1 {font-size: 2.6rem; margin: 0; color: #fff;}
.hero p {font-size: 1.1rem; opacity: .9; margin-top: .5rem;}
div[role="radiogroup"] {gap: .5rem; flex-wrap: wrap;}
div[role="radiogroup"] > label {
    background: rgba(128,128,128,.14); padding: .4rem 1.1rem;
    border-radius: 999px; cursor: pointer;
}
div[role="radiogroup"] > label > div:first-child {display: none;}
div[role="radiogroup"] > label:has(input:checked) {background: #2f5d8a;}
div[role="radiogroup"] > label:has(input:checked) p {color: #fff;}
</style>
"""


def hero_background():
    """Use library.jpg/.png/.webp from the app folder, else a gradient."""
    for name, mime in (("library.jpg", "jpeg"), ("library.jpeg", "jpeg"),
                       ("library.png", "png"), ("library.webp", "webp")):
        path = DATA_DIR / name
        if path.exists():
            data = base64.b64encode(path.read_bytes()).decode()
            return f"url(data:image/{mime};base64,{data})"
    return "linear-gradient(135deg, #1e3a5f, #8b5e34)"


st.markdown(STYLE.replace("__BG__", hero_background()), unsafe_allow_html=True)


# ---------------- Neon PostgreSQL helpers ----------------
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

@st.cache_resource
def get_engine():
    # Store the Neon connection string in .streamlit/secrets.toml locally
    # and in Streamlit Cloud -> Settings -> Secrets when deployed.
    url = st.secrets["connections"]["neon"]["url"]
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(
    url.replace("postgresql://", "postgresql+psycopg2://", 1),
    pool_pre_ping=True,
    pool_recycle=300
)

def db_read_records(path, expected_fields):
    try:
        engine = get_engine()
        with engine.connect() as conn:
            if path.name == "book_data.txt":
                rows = conn.execute(text("""
                    SELECT id, title, author, available_copies
                    FROM books WHERE is_active = TRUE ORDER BY id
                """)).fetchall()
                return [[str(r[0]), r[1], r[2], str(r[3])] for r in rows]
            if path.name == "user_data.txt":
                rows = conn.execute(text("""
                    SELECT id, name, email FROM users ORDER BY id
                """)).fetchall()
                return [[str(r[0]), r[1], r[2] or ""] for r in rows]
            if path.name == "issue_data.txt":
                rows = conn.execute(text("""
                    SELECT id, user_id, book_id, issue_date, status
                    FROM issues ORDER BY id
                """)).fetchall()
                return [[str(r[0]), str(r[1] or ""), str(r[2]),
                         r[3].isoformat() if r[3] else "", r[4]] for r in rows]
    except (SQLAlchemyError, KeyError) as exc:
        st.error("Could not read Neon database. Check the connection string and database tables.")
        st.exception(exc)
    return []

def db_write_records(path, records):
    try:
        engine = get_engine()
        with engine.begin() as conn:
            if path.name == "book_data.txt":
                for row in records:
                    if len(row) != 4:
                        continue
                    book_id, title, author, available = row
                    available = max(0, int(available))
                    conn.execute(text("""
                        INSERT INTO books (id, title, author, total_copies, available_copies, is_active)
                        VALUES (:id, :title, :author, :available, :available, TRUE)
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title,
                            author = EXCLUDED.author,
                            total_copies = GREATEST(books.total_copies, EXCLUDED.total_copies),
                            available_copies = EXCLUDED.available_copies,
                            is_active = TRUE
                    """), {"id": int(book_id), "title": title, "author": author,
                           "available": available})
                conn.execute(text("""
                    SELECT setval(pg_get_serial_sequence('books','id'),
                                  GREATEST(COALESCE((SELECT MAX(id) FROM books), 1), 1),
                                  (SELECT COUNT(*) > 0 FROM books))
                """))
            elif path.name == "user_data.txt":
                for row in records:
                    if len(row) != 3:
                        continue
                    user_id, name, email = row
                    if not email.strip():
                        st.error("A valid email is required to register a user in Neon.")
                        return False
                    conn.execute(text("""
                        INSERT INTO users (id, name, email)
                        VALUES (:id, :name, :email)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, email = EXCLUDED.email
                    """), {"id": int(user_id), "name": name, "email": email.lower()})
                conn.execute(text("""
                    SELECT setval(pg_get_serial_sequence('users','id'),
                                  GREATEST(COALESCE((SELECT MAX(id) FROM users), 1), 1),
                                  (SELECT COUNT(*) > 0 FROM users))
                """))
            elif path.name == "issue_data.txt":
                for row in records:
                    if len(row) != 5:
                        continue
                    issue_id, user_id, book_id, issue_date, status = row
                    if not user_id or not book_id:
                        continue
                    book_info = conn.execute(text(
                        "SELECT title, author FROM books WHERE id = :id"
                    ), {"id": int(book_id)}).fetchone()
                    if not book_info:
                        continue
                    conn.execute(text("""
                        INSERT INTO issues
                            (id, user_id, book_id, book_title, book_author, issue_date, status)
                        VALUES
                            (:id, :user_id, :book_id, :title, :author, CAST(:issue_date AS DATE), :status)
                        ON CONFLICT (id) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            book_id = EXCLUDED.book_id,
                            book_title = EXCLUDED.book_title,
                            book_author = EXCLUDED.book_author,
                            issue_date = EXCLUDED.issue_date,
                            status = EXCLUDED.status,
                            return_date = CASE WHEN EXCLUDED.status = 'returned'
                                               THEN COALESCE(issues.return_date, CURRENT_DATE)
                                               ELSE NULL END
                    """), {"id": int(issue_id), "user_id": int(user_id), "book_id": int(book_id),
                           "title": book_info[0], "author": book_info[1],
                           "issue_date": issue_date, "status": status.lower()})
                conn.execute(text("""
                    SELECT setval(pg_get_serial_sequence('issues','id'),
                                  GREATEST(COALESCE((SELECT MAX(id) FROM issues), 1), 1),
                                  (SELECT COUNT(*) > 0 FROM issues))
                """))
        return True
    except (SQLAlchemyError, ValueError, KeyError) as exc:
        st.error("Could not save changes to Neon. Check the database schema and records.")
        st.exception(exc)
        return False

def read_records(path, expected_fields):
    return db_read_records(path, expected_fields)

def write_records(path, records):
    return db_write_records(path, records)

def next_id(records):
    numeric_ids = [int(row[0]) for row in records if row and row[0].isdigit()]
    return max(numeric_ids, default=0) + 1

def find_user(users, user_id):
    return next((user for user in users if user[0] == str(user_id).strip()), None)


def migrate_legacy_files_once():
    """Import legacy CSV-style .txt data only when the Neon app tables are empty.
    Original files are never changed or deleted.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            counts = conn.execute(text("""
                SELECT
                  (SELECT COUNT(*) FROM books) +
                  (SELECT COUNT(*) FROM users) +
                  (SELECT COUNT(*) FROM issues)
            """)).scalar_one()
        if counts:
            return
        legacy = {}
        for filename, fields in ((BOOKS_FILE, 4), (USERS_FILE, 3), (ISSUES_FILE, 5)):
            rows = []
            if filename.exists():
                with filename.open("r", newline="", encoding="utf-8") as f:
                    for row in csv.reader(f):
                        if len(row) == fields:
                            rows.append([v.strip() for v in row])
            legacy[filename] = rows
        # Parents first, then issues so foreign-key references can resolve.
        if legacy[BOOKS_FILE]:
            db_write_records(BOOKS_FILE, legacy[BOOKS_FILE])
        if legacy[USERS_FILE]:
            db_write_records(USERS_FILE, legacy[USERS_FILE])
        if legacy[ISSUES_FILE]:
            db_write_records(ISSUES_FILE, legacy[ISSUES_FILE])
    except (SQLAlchemyError, OSError, KeyError, csv.Error):
        # The app will display a connection error on normal data access.
        pass

migrate_legacy_files_once()


# ---------------- Authentication (Gmail OTP) ----------------
def hash_otp(otp):
    return hashlib.sha256(otp.encode()).hexdigest()


def can_login(role, email):
    if role == "librarian":
        return email in {e.lower() for e in st.secrets["auth"]["allowed_emails"]}
    local, _, domain = email.partition("@")
    return (
        bool(local) and email.count("@") == 1 and " " not in email
        and "@" + domain == STUDENT_DOMAIN
    )


def get_or_create_student(email):
    """Find the member with this email, or add them on first login."""
    members = read_records(USERS_FILE, 3)
    student = next((u for u in members if u[2].lower() == email), None)
    if student:
        return student
    local = email.split("@")[0]
    for ch in "._-":
        local = local.replace(ch, " ")
    name = "".join(c for c in local if not c.isdigit()).title().strip() or local
    student = [str(next_id(members)), name, email]
    return student if write_records(USERS_FILE, members + [student]) else None


def send_otp_email(to_addr, otp):
    cfg = st.secrets["email"]
    msg = EmailMessage()
    msg["Subject"] = "Your Library System login code"
    msg["From"] = cfg["sender"]
    msg["To"] = to_addr
    msg.set_content(
        f"Your one-time code is {otp}.\nIt expires in {OTP_TTL // 60} minutes. "
        "If you didn't request it, you can ignore this email."
    )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
        server.login(cfg["sender"], cfg["app_password"].replace(" ", ""))
        server.send_message(msg)


def start_otp(email, role):
    otp = f"{secrets.randbelow(10**6):06d}"
    try:
        send_otp_email(email, otp)
    except (smtplib.SMTPException, OSError):
        st.error("Could not send the email. Check your secrets.toml and Gmail App Password.")
        return False
    st.session_state.update(
        otp_hash=hash_otp(otp), otp_email=email, otp_role=role,
        otp_expires=time.time() + OTP_TTL, otp_sent_at=time.time(), otp_attempts=0,
    )
    return True


def clear_otp():
    for key in [k for k in st.session_state if k.startswith("otp_")]:
        del st.session_state[key]


def login_panel(role):
    ss = st.session_state
    if role == "student":
        st.caption(f"Sign in with your institute email ({STUDENT_DOMAIN}).")

    # Step 1: email
    if ss.get("otp_role") != role or "otp_hash" not in ss:
        with st.form(f"email_form_{role}"):
            email = st.text_input("Email address").strip().lower()
            go = st.form_submit_button("Send code", type="primary")
        if go:
            if can_login(role, email):
                if start_otp(email, role):
                    st.rerun()
            elif role == "student":
                st.error(f"Please use your institute email ending in {STUDENT_DOMAIN}.")
            else:
                st.info("If this email is authorised, a code has been sent.")
        return

    # Step 2: verify
    st.write(f"A 6-digit code was sent to **{ss['otp_email']}**.")
    with st.form(f"otp_form_{role}"):
        code = st.text_input("Enter code", max_chars=6).strip()
        verify = st.form_submit_button("Verify", type="primary")

    if verify:
        if time.time() > ss["otp_expires"]:
            st.error("Code expired. Request a new one.")
        elif ss["otp_attempts"] >= MAX_ATTEMPTS:
            st.error("Too many attempts. Request a new code.")
        elif secrets.compare_digest(hash_otp(code), ss["otp_hash"]):
            email = ss["otp_email"]
            student = get_or_create_student(email) if role == "student" else None
            if role == "librarian" or student:
                ss["role"], ss["email"], ss["authenticated"] = role, email, True
                if student:
                    ss["user_id"], ss["user_name"] = student[0], student[1]
                clear_otp()
                st.rerun()
        else:
            ss["otp_attempts"] += 1
            st.error(f"Incorrect code. {MAX_ATTEMPTS - ss['otp_attempts']} attempt(s) left.")

    wait = RESEND_COOLDOWN - (time.time() - ss["otp_sent_at"])
    col_a, col_b = st.columns(2)
    if col_a.button("Resend code", key=f"resend_{role}", disabled=wait > 0):
        if start_otp(ss["otp_email"], role):
            st.rerun()
    if wait > 0:
        col_a.caption(f"Resend available in {int(wait) + 1}s")
    if col_b.button("Use a different email", key=f"change_{role}"):
        clear_otp()
        st.rerun()


def require_login():
    if st.session_state.get("authenticated"):
        return
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown(
            """<div class="hero"><h1>📚 Library Management</h1>
            <p>Browse, borrow and manage books, all in one place.</p></div>""",
            unsafe_allow_html=True,
        )
    with right:
        st.write("")
        st.write("")
        st.markdown("## Welcome back")
        st.caption("Sign in with a one-time code sent to your email.")
        tab_lib, tab_stu = st.tabs(["🧑‍💼 Librarian", "🎓 Student"])
        with tab_lib:
            login_panel("librarian")
        with tab_stu:
            login_panel("student")
    st.stop()  # nothing below runs until the user is authenticated


require_login()

# ---------------- Load data ----------------
ss = st.session_state
role = ss["role"]
books = read_records(BOOKS_FILE, 4)
users = read_records(USERS_FILE, 3)
issues = read_records(ISSUES_FILE, 5)


# ---------------- Shared views ----------------
def catalogue():
    query = st.text_input("Search by book ID or title", placeholder="e.g. 3 or Harry Potter")
    filtered = books
    if query.strip():
        normalized = query.strip().casefold()
        filtered = [b for b in books if b[0] == normalized or normalized in b[1].casefold()]
    if filtered:
        st.dataframe(
            [{"Book ID": b[0], "Book Name": b[1], "Author": b[2], "Available Copies": b[3]}
             for b in filtered],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No matching books found." if query.strip() else "No books in the catalogue yet.")


def history_table(rows, show_user=True):
    out = []
    for issue in rows[::-1]:
        user = find_user(users, issue[1])
        book = next((b for b in books if b[0] == issue[2]), None)
        row = {"Issue ID": issue[0]}
        if show_user:
            row["User"] = user[1] if user else f"User {issue[1]}"
        row.update({
            "Book": book[1] if book else f"Book {issue[2]}",
            "Issue Date": issue[3],
            "Status": issue[4].title(),
        })
        out.append(row)
    st.dataframe(out, use_container_width=True, hide_index=True)


# ---------------- Header + top navigation ----------------
head_l, head_r = st.columns([4, 1.2])
head_l.title("📚 Library Management System")
with head_r:
    who = "Librarian" if role == "librarian" else ss.get("user_name", "Student")
    st.caption(f"Signed in as **{who}** ({role})")
    if st.button("Log out"):
        st.session_state.clear()
        st.rerun()

page = st.radio(
    "Section", LIB_PAGES if role == "librarian" else STU_PAGES,
    horizontal=True, label_visibility="collapsed",
)
st.divider()

# ================= LIBRARIAN PAGES =================
if page == "Dashboard":
    active_issues = [i for i in issues if i[4].casefold() == "issued"]
    total_copies = sum(int(b[3]) for b in books if b[3].isdigit())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Book titles", len(books))
    c2.metric("Available copies", total_copies)
    c3.metric("Registered users", len(users))
    c4.metric("Books currently issued", len(active_issues))

    st.subheader("Recently added books")
    if books:
        st.dataframe(
            [{"Book ID": b[0], "Book Name": b[1], "Author": b[2], "Available": b[3]}
             for b in books[-5:][::-1]],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No books have been added yet. Open **Add Book** to get started.")

elif page == "Add Book":
    st.subheader("Add a new book")
    with st.form("add_book_form", clear_on_submit=True):
        book_name = st.text_input("Book name")
        author = st.text_input("Author")
        quantity = st.number_input("Quantity", min_value=1, max_value=100000, value=1, step=1)
        submitted = st.form_submit_button("Add book", type="primary")

    if submitted:
        book_name, author = book_name.strip(), author.strip()
        if not book_name or not author:
            st.error("Please enter both a book name and an author.")
        elif any(b[1].casefold() == book_name.casefold() for b in books):
            st.warning("A book with this name already exists. Use the existing record instead.")
        else:
            book_id = str(next_id(books))
            updated = books + [[book_id, book_name, author, str(int(quantity))]]
            if write_records(BOOKS_FILE, updated):
                books = updated
                st.success(f"Added **{book_name}** successfully. Book ID: **{book_id}**")

elif page == "Books":
    st.subheader("Book catalogue")
    catalogue()

elif page == "Register User":
    st.subheader("Register a library user")
    st.caption(
        f"Students are added automatically when they first sign in with their "
        f"{STUDENT_DOMAIN} email. Use this form only to add someone manually."
    )
    with st.form("register_user_form", clear_on_submit=True):
        user_name = st.text_input("Full name")
        email = st.text_input(f"Email address (students use {STUDENT_DOMAIN})")
        submitted = st.form_submit_button("Register user", type="primary")

    if submitted:
        user_name, email = user_name.strip(), email.strip().lower()
        if not user_name:
            st.error("Please enter the user's name.")
        elif not email or "@" not in email or " " in email:
            st.error("Please enter a valid email address.")
        elif any(u[1].casefold() == user_name.casefold() for u in users):
            st.warning("A user with this name is already registered.")
        elif any(u[2].lower() == email for u in users):
            st.warning("This email is already registered to another user.")
        else:
            user_id = str(next_id(users))
            updated = users + [[user_id, user_name, email]]
            if write_records(USERS_FILE, updated):
                users = updated
                st.success(f"Registered **{user_name}**. User ID: **{user_id}**")

    st.divider()
    st.subheader("Registered users")
    if users:
        st.dataframe(
            [{"User ID": u[0], "Name": u[1], "Email": u[2] or "—"} for u in users],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No users registered yet.")

elif page == "Issue Book":
    st.subheader("Issue a book")
    available_books = [b for b in books if b[3].isdigit() and int(b[3]) > 0]
    if not users:
        st.warning("Register a user before issuing a book.")
    elif not available_books:
        st.warning("No books are currently available to issue.")
    else:
        user_options = {f"{u[1]} (ID {u[0]})": u[0] for u in users}
        book_options = {
            f"{b[1]} — {b[2]} (ID {b[0]}, available: {b[3]})": b[0] for b in available_books
        }
        with st.form("issue_book_form", clear_on_submit=True):
            user_label = st.selectbox("Registered user", list(user_options))
            book_label = st.selectbox("Book", list(book_options))
            submitted = st.form_submit_button("Issue book", type="primary")

        if submitted:
            user_id, book_id = user_options[user_label], book_options[book_label]
            current_books = read_records(BOOKS_FILE, 4)
            current_issues = read_records(ISSUES_FILE, 5)
            book = next((b for b in current_books if b[0] == book_id), None)

            if not book or not book[3].isdigit() or int(book[3]) < 1:
                st.error("This book is no longer available.")
            else:
                book[3] = str(int(book[3]) - 1)
                issue_date = datetime.now().strftime("%Y-%m-%d")
                new_issue = [str(next_id(current_issues)), user_id, book_id, issue_date, "issued"]
                if write_records(BOOKS_FILE, current_books):
                    if write_records(ISSUES_FILE, current_issues + [new_issue]):
                        st.success(f"Issued **{book[1]}** to **{user_label}** on {issue_date}.")
                        st.info(f"Remaining copies: {book[3]}")

elif page == "Return Book":
    st.subheader("Return an issued book")
    active_issues = [i for i in issues if i[4].casefold() == "issued"]

    if not active_issues:
        st.info("There are no books awaiting return.")
    else:
        active_options = {}
        for issue in active_issues:
            user = find_user(users, issue[1])
            book = next((b for b in books if b[0] == issue[2]), None)
            u_label = user[1] if user else f"User {issue[1]}"
            b_label = book[1] if book else f"Book {issue[2]}"
            active_options[
                f"Issue #{issue[0]} — {b_label} / {u_label} (issued {issue[3]})"
            ] = issue[0]

        with st.form("return_book_form"):
            selected_label = st.selectbox("Select an issued book", list(active_options))
            submitted = st.form_submit_button("Confirm return", type="primary")

        if submitted:
            issue_id = active_options[selected_label]
            current_issues = read_records(ISSUES_FILE, 5)
            current_books = read_records(BOOKS_FILE, 4)
            target_issue = next(
                (i for i in current_issues if i[0] == issue_id and i[4].casefold() == "issued"),
                None,
            )
            target_book = (
                next((b for b in current_books if b[0] == target_issue[2]), None)
                if target_issue else None
            )
            if not target_issue or not target_book:
                st.error("Could not find this issue record or book.")
            elif not target_book[3].isdigit():
                st.error("The stored book quantity is invalid.")
            else:
                target_book[3] = str(int(target_book[3]) + 1)
                target_issue[4] = "returned"
                if write_records(BOOKS_FILE, current_books) and write_records(ISSUES_FILE, current_issues):
                    st.success(f"Return recorded for **{target_book[1]}**.")

elif page == "History":
    st.subheader("Issue history")
    if issues:
        history_table(issues)
    else:
        st.info("No issue records yet.")

# ================= STUDENT PAGES =================
elif page == "My Dashboard":
    mine = [i for i in issues if i[1] == ss.get("user_id")]
    current = [i for i in mine if i[4].casefold() == "issued"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Books I currently have", len(current))
    c2.metric("Total books borrowed", len(mine))
    c3.metric("Titles in library", len(books))

    st.subheader("Books I need to return")
    if current:
        history_table(current, show_user=False)
    else:
        st.info("You have no books checked out right now.")

elif page == "Browse Books":
    st.subheader("Book catalogue")
    catalogue()

elif page == "My History":
    st.subheader("My borrowing history")
    mine = [i for i in issues if i[1] == ss.get("user_id")]
    if mine:
        history_table(mine, show_user=False)
    else:
        st.info("You haven't borrowed any books yet.")
