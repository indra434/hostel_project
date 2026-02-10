from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import os
import uuid
from sqlite3 import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import smtplib
from email.message import EmailMessage
import time
import google.generativeai as genai
app = Flask(__name__)
app.secret_key = "hostel_secret"
UPLOAD_FOLDER = "static/uploads"
from dotenv import load_dotenv # Add this at the top with other imports
load_dotenv() 

# This pulls the key from your .env file automatically
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

model = genai.GenerativeModel( 'gemini-3-flash-preview' )
os.makedirs(UPLOAD_FOLDER, exist_ok=True)



# database
def get_db():
    db = sqlite3.connect("database.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db():
    if not os.path.exists("database.db"):
        db = get_db()
        with open("database.sql") as f:
            db.executescript(f.read())

        db.execute("""
            INSERT INTO users(username,password,role,approved)
            VALUES (?,?,?,1)
        """, ("admin", generate_password_hash("admin123"), "admin"))

        db.commit()
        db.close()
        print("Database initialized")

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        db.close()

        if user and check_password_hash(user["password"], p):
            if user["approved"] == 0:
                flash("Account waiting for approval")
                return redirect("/")

            session["uid"] = user["id"]
            session["role"] = user["role"]
            session["college"] = user["college"]
            session["username"] = user["username"]
            return redirect(f"/{user['role']}")

        flash("Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------------- REGISTER ----------------
@app.route("/register/<role>", methods=["GET", "POST"])
def register(role):
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])
        college = request.form.get("college")
        email = request.form.get("email")
        phone = request.form.get("phone")

        id_card = None
        if role == "student":
            file = request.files["id_card"]
            id_card = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file.save(os.path.join(UPLOAD_FOLDER, id_card))

        db = get_db()
        try:
            db.execute("""
                INSERT INTO users
                (username, password, email, phone, role, college, id_card, approved)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                username,
                password,
                email,
                phone,
                role,
                college,
                id_card
            ))
            db.commit()

        except IntegrityError as e:
            db.close()
            flash("Username / Email / Phone already exists")
            return redirect(f"/register/{role}")

        db.close()
        flash("Registered successfully. Wait for principal approval.")
        return redirect("/")

    return render_template("register.html", role=role)

# ----------------for debug ----------------
@app.route("/debug_users")
def debug_users():
    db = get_db()
    users = db.execute("""
        SELECT id, username, role, college, approved
        FROM users
    """).fetchall()
    db.close()
    return "<br>".join([str(dict(u)) for u in users])
# ---------------- ADMIN ----------------
@app.route("/admin")
def admin():
    if session.get("role") != "admin":
        return redirect("/")

    db = get_db()
    principals = db.execute("""
        SELECT * FROM users WHERE role='principal' AND approved=0
    """).fetchall()

    approved_principals = db.execute("""
        SELECT * FROM users WHERE role='principal' AND approved=1
    """).fetchall()

    college_count = db.execute("""
        SELECT COUNT(DISTINCT college) FROM users WHERE role='principal' AND approved=1
    """).fetchone()[0]

    db.close()
    return render_template("admin_dashboard.html", principals=principals,
                           approved_principals=approved_principals, college_count=college_count)

@app.route("/admin/approve/<int:uid>")
def admin_approve(uid):
    if session.get("role") != "admin":
        return redirect("/")

    db = get_db()
    db.execute("UPDATE users SET approved=1 WHERE id=?", (uid,))
    db.commit()
    db.close()
    return redirect("/admin")


# ---------------- PRINCIPAL DASHBOARD ----------------
@app.route("/principal")
def principal():
    if session.get("role") != "principal":
        return redirect("/")

    db = get_db()

    # Pending students & wardens of this college
    pending_users = db.execute("""
    SELECT * FROM users
    WHERE role IN ('student','warden')
    AND approved=0
""").fetchall()

    # Count total approved students in this college
    student_count = db.execute("""
        SELECT COUNT(*) FROM users 
        WHERE role='student' AND college=? AND approved=1
    """, (session["college"],)).fetchone()[0]

    # Pending hostel applications (students only)
    applications = db.execute("""
        SELECT a.id, u.username, h.name, r.room_number, h.id AS hostel_id, u.id AS student_id
        FROM applications a
        JOIN users u ON a.student_id=u.id
        JOIN hostels h ON a.hostel_id=h.id
        LEFT JOIN rooms r ON a.room_id=r.id
        WHERE a.status='pending'
        AND u.college=?
    """, (session["college"],)).fetchall()

    db.close()
    return render_template("principal_dashboard.html",
                           students=pending_users,
                           apps=applications,
                           student_count=student_count)

# ---------------- APPROVE STUDENT/WARDEN ----------------
@app.route("/principal/approve_user/<int:uid>")
def principal_approve_user(uid):
    if session.get("role") != "principal":
        return redirect("/")

    db = get_db()
    db.execute("UPDATE users SET approved=1 WHERE id=?", (uid,))
    db.commit()
    db.close()
    flash("User approved successfully")
    return redirect("/principal")

# ---------------- REJECT STUDENT/WARDEN ----------------
@app.route("/principal/reject_user/<int:uid>")
def principal_reject_user(uid):
    if session.get("role") != "principal":
        return redirect("/")

    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    db.close()
    flash("User rejected successfully")
    return redirect("/principal")

# ---------------- APPROVE HOSTEL APPLICATION ----------------
@app.route("/principal/approve_hostel/<int:aid>")
def principal_approve_hostel(aid):
    if session.get("role") != "principal":
        return redirect("/")

    db = get_db()
    app_data = db.execute("""
        SELECT student_id, hostel_id, room_id
        FROM applications
        WHERE id=?
    """, (aid,)).fetchone()

    if app_data:
        # 1. Try to allocate the specific room applied for
        room = db.execute("""
            SELECT id FROM rooms
            WHERE id=? AND occupied < capacity
        """, (app_data["room_id"],)).fetchone()

        # 2. If that room is full, fallback to any available room in the hostel
        if not room:
            room = db.execute("""
                SELECT id FROM rooms
                WHERE hostel_id=? AND occupied < capacity
                LIMIT 1
            """, (app_data["hostel_id"],)).fetchone()

        if room:
            db.execute("""
                UPDATE rooms
                SET occupied = occupied + 1
                WHERE id=?
            """, (room["id"],))

            db.execute("""
                UPDATE users
                SET room_id=?
                WHERE id=?
            """, (room["id"], app_data["student_id"]))

            db.execute("""
                UPDATE hostels
                SET available_rooms = available_rooms - 1
                WHERE id=?
            """, (app_data["hostel_id"],))

        db.execute("""
            UPDATE applications
            SET status='approved'
            WHERE id=?
        """, (aid,))

    db.commit()
    db.close()
    flash("Hostel request approved")
    return redirect("/principal")

# ---------------- STUDENT ----------------

@app.route("/student")
def student():
    if session.get("role") != "student":
        return redirect("/")

    db = get_db()

    # Available rooms (not allocated)
    rooms = db.execute("""
        SELECT r.*, h.name AS hostel_name
        FROM rooms r
        JOIN hostels h ON r.hostel_id = h.id
        WHERE h.college = ?
    """, (session["college"],)).fetchall()

    # Student attendance
    attendance = db.execute("""
        SELECT date, status
        FROM attendance
        WHERE student_id = ?
        ORDER BY date DESC
    """, (session["uid"],)).fetchall()

    # Photos (room-wise)
    photos = db.execute("""
        SELECT rp.filename, r.room_number, h.name AS hostel_name
        FROM room_photos rp
        JOIN rooms r ON rp.room_id = r.id
        JOIN hostels h ON rp.hostel_id = h.id
        WHERE h.college = ?
    """, (session["college"],)).fetchall()

    # Allocated room (if already approved)
    room = db.execute("""
        SELECT r.*, h.name AS hostel_name
        FROM rooms r
        JOIN hostels h ON r.hostel_id = h.id
        JOIN users u ON u.room_id = r.id
        WHERE u.id = ?
    """, (session["uid"],)).fetchone()

    db.close()

    return render_template(
        "student_dashboard.html",
        rooms=rooms,
        attendance=attendance,
        photos=photos,
        room=room
    )


@app.route("/student/apply_room/<int:room_id>")
def apply_room(room_id):
    if session.get("role") != "student":
        return redirect("/")

    db = get_db()

    hostel = db.execute("""
        SELECT hostel_id FROM rooms WHERE id=?
    """, (room_id,)).fetchone()

    if hostel:
        db.execute("""
            INSERT INTO applications (student_id, hostel_id, room_id, status)
            VALUES (?, ?, ?, 'pending')
        """, (session["uid"], hostel["hostel_id"], room_id))

    db.commit()
    db.close()

    flash("Room application sent to principal")
    return redirect("/student")
# ---------------- WARDEN DASHBOARD ----------------
@app.route("/warden")
def warden():
    if session.get("role") != "warden":
        return redirect("/")

    db = get_db()

    # Approved students of same college
    students = db.execute("""
        SELECT id, username 
        FROM users
        WHERE role='student' AND approved=1 AND college=?
    """, (session["college"],)).fetchall()

    # Attendance taken by this warden
    attendance = db.execute("""
        SELECT u.username, a.date, a.status
        FROM attendance a
        JOIN users u ON a.student_id = u.id
        WHERE a.warden_id=?
        ORDER BY a.date DESC
    """, (session["uid"],)).fetchall()

    # Hostels created by this warden
    hostels = db.execute("""
        SELECT * FROM hostels
        WHERE warden_id=?
    """, (session["uid"],)).fetchall()

    # Rooms of those hostels
    rooms = db.execute("""
        SELECT r.*, h.name AS hostel_name
        FROM rooms r
        JOIN hostels h ON r.hostel_id = h.id
        WHERE h.warden_id=?
    """, (session["uid"],)).fetchall()

    # Uploaded photos (room-wise)
    photos = db.execute("""
        SELECT rp.filename, r.room_number, h.name AS hostel_name
        FROM room_photos rp
        JOIN rooms r ON rp.room_id = r.id
        JOIN hostels h ON rp.hostel_id = h.id
        WHERE rp.warden_id=? AND h.college=?
    """, (session["uid"], session["college"])).fetchall()

    db.close()

    return render_template(
        "warden_dashboard.html",
        students=students,
        attendance=attendance,
        hostels=hostels,
        rooms=rooms,
        photos=photos
    )


# ---------------- ADD HOSTEL ----------------
@app.route("/warden/add_hostel", methods=["POST"])
def warden_add_hostel():
    if session.get("role") != "warden":
        return redirect("/")

    name = request.form["hostel_name"]
    total_rooms = int(request.form["total_rooms"])

    db = get_db()

    cur = db.execute("""
        INSERT INTO hostels (name, college, warden_id, total_rooms, available_rooms)
        VALUES (?,?,?,?,?)
    """, (
        name,
        session["college"],
        session["uid"],
        total_rooms,
        total_rooms
    ))

    hostel_id = cur.lastrowid

    # auto-create room numbers
    for i in range(1, total_rooms + 1):
        db.execute("""
            INSERT INTO rooms (hostel_id, room_number)
            VALUES (?,?)
        """, (hostel_id, f"R{i}"))

    db.commit()
    db.close()

    flash("Hostel added successfully!")
    return redirect("/warden")

# ---------------- UPDATE ROOM DETAILS ----------------
@app.route("/warden/update_room", methods=["POST"])
def warden_update_room():
    if session.get("role") != "warden":
        return redirect("/")

    room_id = request.form["room_id"]
    capacity = request.form["capacity"]
    facilities = request.form["facilities"]
    damage = request.form["damage"]

    db = get_db()
    db.execute("""
        UPDATE rooms SET capacity=?, facilities=?, damage=? WHERE id=?
    """, (capacity, facilities, damage, room_id))
    db.commit()
    db.close()

    flash("Room details updated!")
    return redirect("/warden")

# ---------------- TAKE ATTENDANCE ----------------
@app.route("/warden/attendance", methods=["POST"])
def warden_attendance():
    if session.get("role") != "warden":
        return redirect("/")

    student_id = request.form["student_id"]
    date = request.form["date"]
    status = request.form["status"]

    db = get_db()
    db.execute("""
        INSERT INTO attendance (student_id, warden_id, date, status)
        VALUES (?,?,?,?)
    """, (student_id, session["uid"], date, status))

    db.commit()
    db.close()

    flash("Attendance marked!")
    return redirect("/warden")

# ---------------- Forgot password ----------------
# ---------------- Forgot password ----------------
import random

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        contact = request.form.get("contact", "").strip()  # ✅ IMPORTANT

        print("CONTACT ENTERED:", repr(contact))  # ✅ DEBUG

        if not contact:
            return render_template(
                "forgot_password.html",
                error="Please enter email or mobile number"
            )

        db = get_db()
        user = db.execute("""
            SELECT * FROM users
            WHERE email = ? OR phone = ?
        """, (contact, contact)).fetchone()

        print("USER FOUND:", user)  # ✅ DEBUG

        if not user:
            db.close()
            return render_template(
                "forgot_password.html",
                error="No account found with this email or mobile number"
            )

        otp = random.randint(100000, 999999)

        session["reset_otp"] = str(otp)
        session["reset_uid"] = user["id"]
        session["otp_time"] = time.time()

        send_otp_email(user["email"], otp)

        db.close()
        return render_template("verify_otp.html")

    return render_template("forgot_password.html")
    
# ---------------- OTP VERIFICATION ----------------
@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    entered_otp = request.form.get("otp")

    # Safety: session missing
    if "reset_otp" not in session or "otp_time" not in session:
        flash("Session expired. Try again.")
        return redirect("/forgot_password")

    # OTP expiry check (5 minutes)
    if time.time() - session["otp_time"] > 300:
        session.clear()
        flash("OTP expired. Please request again.")
        return redirect("/forgot_password")

    # Wrong OTP
    if entered_otp != session["reset_otp"]:
        return render_template(
            "verify_otp.html",
            error="Invalid OTP"
        )

    # Correct OTP
    return redirect("/reset_password")
# ----------------  for new password ----------------
@app.route("/reset_password", methods=["GET","POST"])
def reset_password():
    if request.method == "POST":
        hashed = generate_password_hash(request.form["password"])

        db = get_db()
        db.execute(
            "UPDATE users SET password=? WHERE id=?",
            (hashed, session["reset_uid"])
        )
        db.commit()
        db.close()

        session.clear()
        flash("Password updated successfully")
        return redirect("/")

    return render_template("reset_password.html")
# ---------------- UPLOAD ROOM PHOTO ----------------
@app.route("/warden/photo", methods=["POST"])
def warden_photo():
    if session.get("role") != "warden":
        return redirect("/")

    file = request.files["photo"]
    hostel_id = request.form.get("hostel_id")
    room_id = request.form.get("room_id")

    if not file or not hostel_id or not room_id:
        flash("Please select a hostel, room, and file")
        return redirect("/warden")

    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    file.save(os.path.join(UPLOAD_FOLDER, filename))

    db = get_db()
    # Ensure the hostel and room belong to this warden and college
    valid = db.execute("""
        SELECT r.id FROM rooms r
        JOIN hostels h ON r.hostel_id = h.id
        WHERE r.id=? AND h.id=? AND h.warden_id=? AND h.college=?
    """, (room_id, hostel_id, session["uid"], session["college"])).fetchone()

    if valid:
        db.execute("""
            INSERT INTO room_photos (hostel_id, room_id, warden_id, filename)
            VALUES (?,?,?,?)
        """, (hostel_id, room_id, session["uid"], filename))
        db.commit()
        flash("Photo uploaded successfully")
    else:
        flash("Invalid room or hostel selection")

    db.close()
    return redirect("/warden")
# for otp mail
def send_otp_email(to_email, otp):
    EMAIL_ADDRESS = "indrakumar3995@gmail.com"
    EMAIL_PASSWORD = "vrcyysgxcnlyoztu"

    msg = EmailMessage()
    msg["Subject"] = "Hostel System - OTP Verification"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    msg.set_content(f"""
Your OTP is: {otp}

This OTP is valid for 5 minutes.
Do not share it with anyone.
""")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
# ---------------- RUN ----------------
# ---------------- AI BOT ROUTE ----------------
@app.route("/chat", methods=["POST"])
def chat():
    # Only allow logged-in users to chat
    if "username" not in session:
        return {"response": "Please login first!"}, 401

    data = request.json
    user_message = data.get("message")
    
    # System Instruction: Tells the AI its job
    prompt = f"You are a helpful Hostel Assistant for MNR College. The user is {session.get('username')}. Answer: {user_message}"
    
    try:
        # Gemini 3 Flash is optimized for these agent-first interactions
        response = model.generate_content(prompt)
        return {"response": response.text}
    except Exception as e:
        print(f"Error: {e}")
        return {"response": "I'm having trouble thinking right now. Try again later!"}, 500
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=10000)