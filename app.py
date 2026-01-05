from flask import Flask, render_template, request, redirect, session, flash
import sqlite3, os, uuid
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "hostel_secret"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- DB ----------------
def get_db():
    db = sqlite3.connect("database.db")
    db.row_factory = sqlite3.Row
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
@app.route("/register/<role>", methods=["GET","POST"])
def register(role):
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])
        college = request.form.get("college")

        id_card = None
        if role == "student":
            file = request.files["id_card"]
            id_card = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file.save(os.path.join(UPLOAD_FOLDER, id_card))

        db = get_db()
        db.execute("""
            INSERT INTO users(username,password,role,college,id_card)
            VALUES (?,?,?,?,?)
        """, (username, password, role, college, id_card))
        db.commit()
        db.close()

        flash("Registered successfully. Wait for approval.")
        return redirect("/")

    return render_template(f"{role}_register.html")

# ---------------- ADMIN ----------------
@app.route("/admin")
def admin():
    if session.get("role") != "admin":
        return redirect("/")

    db = get_db()
    principals = db.execute("""
        SELECT * FROM users WHERE role='principal' AND approved=0
    """).fetchall()
    db.close()
    return render_template("admin_dashboard.html", principals=principals)

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
        AND college=?
    """, (session["college"],)).fetchall()

    # Pending hostel applications (students only)
    applications = db.execute("""
        SELECT a.id, u.username, h.name, h.id AS hostel_id, u.id AS student_id
        FROM applications a
        JOIN users u ON a.student_id=u.id
        JOIN hostels h ON a.hostel_id=h.id
        WHERE a.status='pending'
        AND u.college=?
    """, (session["college"],)).fetchall()

    db.close()
    return render_template("principal_dashboard.html",
                           students=pending_users,
                           apps=applications)

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
        SELECT student_id, hostel_id
        FROM applications
        WHERE id=?
    """, (aid,)).fetchone()

    if app_data:
        # Allocate first available room
        room = db.execute("""
            SELECT id FROM rooms
            WHERE hostel_id=? AND is_allocated=0
            LIMIT 1
        """, (app_data["hostel_id"],)).fetchone()

        if room:
            db.execute("""
                UPDATE rooms
                SET is_allocated=1, student_id=?
                WHERE id=?
            """, (app_data["student_id"], room["id"]))

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
        SELECT r.id, r.room_number, h.name AS hostel_name
        FROM rooms r
        JOIN hostels h ON r.hostel_id = h.id
        WHERE r.is_allocated = 0
        AND h.college = ?
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
        SELECT r.room_number, h.name AS hostel_name
        FROM rooms r
        JOIN hostels h ON r.hostel_id = h.id
        WHERE r.student_id = ?
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
            INSERT INTO applications (student_id, hostel_id, status)
            VALUES (?, ?, 'pending')
        """, (session["uid"], hostel["hostel_id"]))

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
        SELECT r.id, r.room_number, h.name AS hostel_name
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
# ---------------- RUN ----------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=10000)