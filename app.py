from flask import Flask, render_template, request, redirect, session
import sqlite3
import hashlib
import os
import difflib
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "cloud_assurance_secret_key"

UPLOAD_FOLDER = "uploads"
DB_NAME = "database.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------- DATABASE ----------------

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- TIME ----------------

def get_ist_time():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ---------------- HASH ----------------

def calculate_hash(filepath):
    sha256 = hashlib.sha256()

    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256.update(block)

    return sha256.hexdigest()


# ---------------- CURRENT USER ----------------

def get_current_user():
    if "user_id" not in session:
        return None

    return session["user_id"]


# ---------------- LOGIN ----------------

@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")

    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password)
        ).fetchone()

        conn.close()

        if user:

            session["user_id"] = user["id"]
            session["username"] = user["username"]

            return redirect("/dashboard")

        return "Invalid username or password"

    return render_template("login.html")


# ---------------- REGISTER ----------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()

        try:

            conn.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )

            conn.commit()
            conn.close()

            return redirect("/login")

        except sqlite3.IntegrityError:

            conn.close()
            return "Username already exists"

    return render_template("register.html")


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
def dashboard():

    if not get_current_user():
        return redirect("/login")

    return render_template(
        "dashboard.html",
        username=session["username"]
    )


# ---------------- MY FILES ----------------

@app.route("/files")
def files():

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    files = conn.execute(
        """
        SELECT *
        FROM files
        WHERE owner_id=?
        ORDER BY id DESC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "files.html",
        files=files
    )


# ---------------- UPLOAD ----------------

@app.route("/upload", methods=["POST"])
def upload():

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    uploaded_file = request.files["file"]

    if uploaded_file.filename == "":
        return "No file selected"

    filename = uploaded_file.filename
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    uploaded_file.save(filepath)

    file_hash = calculate_hash(filepath)
    current_time = get_ist_time()

    conn = get_db()

    existing_file = conn.execute(
        """
        SELECT *
        FROM files
        WHERE filename=? AND owner_id=?
        """,
        (filename, user_id)
    ).fetchone()

    if existing_file:

        conn.execute(
            """
            UPDATE files
            SET file_hash=?, upload_time=?
            WHERE id=?
            """,
            (
                file_hash,
                current_time,
                existing_file["id"]
            )
        )

        version_result = conn.execute(
            """
            SELECT MAX(version_number)
            FROM file_versions
            WHERE filename=?
            """,
            (filename,)
        ).fetchone()

        next_version = (version_result[0] or 0) + 1

    else:

        cursor = conn.execute(
            """
            INSERT INTO files
            (filename, file_hash, upload_time, owner_id)
            VALUES (?, ?, ?, ?)
            """,
            (
                filename,
                file_hash,
                current_time,
                user_id
            )
        )

        file_id = cursor.lastrowid

        next_version = 1

    conn.execute(
        """
        INSERT INTO file_versions
        (filename, file_hash, version_number,
         created_at, modified_by, change_summary)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            file_hash,
            next_version,
            current_time,
            user_id,
            "Initial file upload"
            if next_version == 1
            else "File uploaded again"
        )
    )

    conn.execute(
        """
        INSERT INTO audit_logs
        (username, action, filename, log_time)
        VALUES (?, ?, ?, ?)
        """,
        (
            session["username"],
            "FILE UPLOAD",
            filename,
            current_time
        )
    )

    conn.commit()
    conn.close()

    return redirect("/files")


# ---------------- SHARED WITH ME ----------------

@app.route("/shared")
def shared():

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    files = conn.execute(
        """
        SELECT
            files.id,
            files.filename,
            files.upload_time,
            users.username AS owner_username,
            file_access.permission
        FROM file_access
        JOIN files
            ON file_access.file_id = files.id
        JOIN users
            ON files.owner_id = users.id
        WHERE file_access.user_id=?
        ORDER BY files.id DESC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "shared.html",
        files=files
    )


# ---------------- SHARE FILE ----------------

@app.route("/share/<int:file_id>", methods=["POST"])
def share_file(file_id):

    owner_id = get_current_user()

    if not owner_id:
        return redirect("/login")

    username = request.form["username"]
    permission = request.form["permission"]

    conn = get_db()

    file = conn.execute(
        """
        SELECT *
        FROM files
        WHERE id=? AND owner_id=?
        """,
        (file_id, owner_id)
    ).fetchone()

    if not file:

        conn.close()
        return "Access denied"

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE username=?
        """,
        (username,)
    ).fetchone()

    if not user:

        conn.close()
        return "User not found"

    if user["id"] == owner_id:

        conn.close()
        return "You cannot share a file with yourself"

    existing = conn.execute(
        """
        SELECT *
        FROM file_access
        WHERE file_id=? AND user_id=?
        """,
        (
            file_id,
            user["id"]
        )
    ).fetchone()

    current_time = get_ist_time()

    if existing:

        conn.execute(
            """
            UPDATE file_access
            SET permission=?, granted_at=?
            WHERE file_id=? AND user_id=?
            """,
            (
                permission,
                current_time,
                file_id,
                user["id"]
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO file_access
            (file_id, user_id, permission, granted_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                file_id,
                user["id"],
                permission,
                current_time
            )
        )

    conn.execute(
        """
        INSERT INTO audit_logs
        (username, action, filename, log_time)
        VALUES (?, ?, ?, ?)
        """,
        (
            session["username"],
            "FILE SHARED",
            file["filename"],
            current_time
        )
    )

    conn.commit()
    conn.close()

    return redirect("/files")


# ---------------- EDIT SHARED FILE ----------------

@app.route("/edit/<int:file_id>", methods=["GET", "POST"])
def edit_file(file_id):

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    # Check whether this user has edit permission
    access = conn.execute(
        """
        SELECT
            file_access.permission,
            files.filename,
            files.owner_id
        FROM file_access
        JOIN files
            ON file_access.file_id = files.id
        WHERE file_access.file_id=?
          AND file_access.user_id=?
        """,
        (
            file_id,
            user_id
        )
    ).fetchone()

    if not access:

        conn.close()
        return "You do not have access to this file"

    if access["permission"] != "edit":

        conn.close()
        return "Access denied: You only have view permission"

    filename = access["filename"]

    filepath = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    if not os.path.exists(filepath):

        conn.close()
        return "File not found"

    # -------- GET: SHOW FILE --------

    if request.method == "GET":

        try:

            with open(
                filepath,
                "r",
                encoding="utf-8"
            ) as f:

                content = f.read()

        except UnicodeDecodeError:

            conn.close()
            return "This file type cannot be edited as text"

        conn.close()

        return render_template(
            "edit.html",
            filename=filename,
            content=content
        )

    # -------- POST: SAVE CHANGES --------

    new_content = request.form["content"]

    try:

        with open(
            filepath,
            "r",
            encoding="utf-8"
        ) as f:

            old_content = f.read()

    except UnicodeDecodeError:

        conn.close()
        return "This file type cannot be edited as text"

    # Check if anything changed
    if old_content == new_content:

        conn.close()
        return redirect("/shared")

    # Calculate old and new hash
    old_hash = hashlib.sha256(
        old_content.encode("utf-8")
    ).hexdigest()

    new_hash = hashlib.sha256(
        new_content.encode("utf-8")
    ).hexdigest()

    # Create exact line-level diff
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="Previous Version",
            tofile="New Version",
            lineterm=""
        )
    )

    added_lines = sum(
        1
        for line in diff
        if line.startswith("+")
        and not line.startswith("+++")
    )

    deleted_lines = sum(
        1
        for line in diff
        if line.startswith("-")
        and not line.startswith("---")
    )

    diff_text = "\n".join(diff)

    change_summary = (
        f"Modified by {session['username']} | "
        f"Previous hash: {old_hash} | "
        f"New hash: {new_hash} | "
        f"Added lines: {added_lines} | "
        f"Deleted lines: {deleted_lines}\n\n"
        f"{diff_text}"
    )

    # Save modified file
    with open(
        filepath,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(new_content)

    current_time = get_ist_time()

    # Find next version number
    version_result = conn.execute(
        """
        SELECT MAX(version_number)
        FROM file_versions
        WHERE filename=?
        """,
        (filename,)
    ).fetchone()

    next_version = (version_result[0] or 0) + 1

    # Update main file record
    conn.execute(
        """
        UPDATE files
        SET file_hash=?, upload_time=?
        WHERE id=?
        """,
        (
            new_hash,
            current_time,
            file_id
        )
    )

    # Store new version
    conn.execute(
        """
        INSERT INTO file_versions
        (filename, file_hash, version_number,
         created_at, modified_by, change_summary)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            new_hash,
            next_version,
            current_time,
            user_id,
            change_summary
        )
    )

    # Audit log
    conn.execute(
        """
        INSERT INTO audit_logs
        (username, action, filename, log_time)
        VALUES (?, ?, ?, ?)
        """,
        (
            session["username"],
            "FILE EDIT",
            filename,
            current_time
        )
    )

    conn.commit()
    conn.close()

    return redirect("/history/" + filename)


# ---------------- VERIFY FILE ----------------

@app.route("/verify/<int:file_id>")
def verify(file_id):

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    file = conn.execute(
        """
        SELECT *
        FROM files
        WHERE id=? AND owner_id=?
        """,
        (
            file_id,
            user_id
        )
    ).fetchone()

    if not file:

        shared = conn.execute(
            """
            SELECT files.*
            FROM file_access
            JOIN files
                ON file_access.file_id=files.id
            WHERE file_access.file_id=?
              AND file_access.user_id=?
            """,
            (
                file_id,
                user_id
            )
        ).fetchone()

        file = shared

    if not file:

        conn.close()
        return "Access denied"

    filepath = os.path.join(
        UPLOAD_FOLDER,
        file["filename"]
    )

    if not os.path.exists(filepath):

        conn.close()
        return "File not found"

    current_hash = calculate_hash(filepath)

    original_hash = file["file_hash"]

    if current_hash == original_hash:

        result = "INTEGRITY VERIFIED - File is unchanged"

    else:

        result = "WARNING - File has been modified"

    conn.close()

    return f"""
    <h2>{result}</h2>
    <p><b>Filename:</b> {file["filename"]}</p>
    <p><b>Stored Hash:</b> {original_hash}</p>
    <p><b>Current Hash:</b> {current_hash}</p>
    <a href="/files">Back to Files</a>
    """


# ---------------- VERSION HISTORY ----------------

@app.route("/history/<filename>")
def history(filename):

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    access = conn.execute(
        """
        SELECT *
        FROM files
        WHERE filename=? AND owner_id=?
        """,
        (
            filename,
            user_id
        )
    ).fetchone()

    if not access:

        access = conn.execute(
            """
            SELECT files.*
            FROM file_access
            JOIN files
                ON file_access.file_id=files.id
            WHERE files.filename=?
              AND file_access.user_id=?
            """,
            (
                filename,
                user_id
            )
        ).fetchone()

    if not access:

        conn.close()
        return "Access denied"

    versions = conn.execute(
        """
        SELECT
            file_versions.*,
            users.username AS modified_by_username
        FROM file_versions
        LEFT JOIN users
            ON file_versions.modified_by=users.id
        WHERE file_versions.filename=?
        ORDER BY version_number DESC
        """,
        (filename,)
    ).fetchall()

    conn.close()

    return render_template(
        "history.html",
        filename=filename,
        versions=versions
    )


# ---------------- DOWNLOAD ----------------

@app.route("/download/<filename>")
def download(filename):

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    file = conn.execute(
        """
        SELECT *
        FROM files
        WHERE filename=? AND owner_id=?
        """,
        (
            filename,
            user_id
        )
    ).fetchone()

    if not file:

        file = conn.execute(
            """
            SELECT files.*
            FROM file_access
            JOIN files
                ON file_access.file_id=files.id
            WHERE files.filename=?
              AND file_access.user_id=?
            """,
            (
                filename,
                user_id
            )
        ).fetchone()

    if not file:

        conn.close()
        return "Access denied"

    current_time = get_ist_time()

    conn.execute(
        """
        INSERT INTO audit_logs
        (username, action, filename, log_time)
        VALUES (?, ?, ?, ?)
        """,
        (
            session["username"],
            "FILE DOWNLOAD",
            filename,
            current_time
        )
    )

    conn.commit()
    conn.close()

    filepath = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    if not os.path.exists(filepath):

        return "File not found"

    from flask import send_file

    return send_file(
        filepath,
        as_attachment=True
    )


# ---------------- DELETE ----------------

@app.route("/delete/<filename>")
def delete(filename):

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    file = conn.execute(
        """
        SELECT *
        FROM files
        WHERE filename=? AND owner_id=?
        """,
        (
            filename,
            user_id
        )
    ).fetchone()

    if not file:

        conn.close()
        return "Access denied"

    filepath = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    if os.path.exists(filepath):

        os.remove(filepath)

    current_time = get_ist_time()

    conn.execute(
        """
        INSERT INTO audit_logs
        (username, action, filename, log_time)
        VALUES (?, ?, ?, ?)
        """,
        (
            session["username"],
            "FILE DELETE",
            filename,
            current_time
        )
    )

    conn.execute(
        """
        DELETE FROM file_access
        WHERE file_id=?
        """,
        (file["id"],)
    )

    conn.execute(
        """
        DELETE FROM files
        WHERE id=?
        """,
        (file["id"],)
    )

    conn.commit()
    conn.close()

    return redirect("/files")


# ---------------- AUDIT LOGS ----------------

@app.route("/logs")
def logs():

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    logs_data = conn.execute(
        """
        SELECT *
        FROM audit_logs
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "logs.html",
        logs=logs_data
    )


# ---------------- DIFF ----------------

@app.route("/diff/<filename>")
def diff_file(filename):

    user_id = get_current_user()

    if not user_id:
        return redirect("/login")

    conn = get_db()

    versions = conn.execute(
        """
        SELECT
            file_versions.*,
            users.username AS modified_by_username
        FROM file_versions
        LEFT JOIN users
            ON file_versions.modified_by=users.id
        WHERE file_versions.filename=?
        ORDER BY version_number DESC
        """,
        (filename,)
    ).fetchall()

    conn.close()

    return render_template(
        "history.html",
        filename=filename,
        versions=versions
    )


# ---------------- RUN APP ----------------

if __name__ == "__main__":

    app.run(
        debug=True,
        host="0.0.0.0",
        port=5000
    )