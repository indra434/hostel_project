PRAGMA foreign_keys = ON;

-- =========================
-- USERS
-- =========================
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,

    email TEXT UNIQUE,
    phone TEXT UNIQUE,

    role TEXT CHECK (
        role IN ('admin','principal','student','warden','guardian')
    ) NOT NULL,

    college TEXT,
    approved INTEGER DEFAULT 0,

    id_card TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- HOSTELS
-- =========================
CREATE TABLE hostels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    college TEXT NOT NULL,

    warden_id INTEGER NOT NULL,
    total_rooms INTEGER NOT NULL,
    available_rooms INTEGER NOT NULL,

    FOREIGN KEY (warden_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

-- =========================
-- ROOMS
-- =========================
CREATE TABLE rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hostel_id INTEGER NOT NULL,
    room_number TEXT NOT NULL,

    is_allocated INTEGER DEFAULT 0,
    student_id INTEGER,

    FOREIGN KEY (hostel_id)
        REFERENCES hostels(id)
        ON DELETE CASCADE,

    FOREIGN KEY (student_id)
        REFERENCES users(id)
        ON DELETE SET NULL
);

-- =========================
-- APPLICATIONS
-- =========================
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    student_id INTEGER NOT NULL,
    hostel_id INTEGER NOT NULL,

    status TEXT CHECK (
        status IN ('pending','approved','rejected')
    ) DEFAULT 'pending',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (student_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (hostel_id)
        REFERENCES hostels(id)
        ON DELETE CASCADE
);

-- =========================
-- ATTENDANCE
-- =========================
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    student_id INTEGER NOT NULL,
    warden_id INTEGER NOT NULL,

    date TEXT NOT NULL,
    status TEXT CHECK (
        status IN ('present','absent')
    ) NOT NULL,

    FOREIGN KEY (student_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    FOREIGN KEY (warden_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

-- =========================
-- ROOM PHOTOS
-- =========================
CREATE TABLE room_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    hostel_id INTEGER NOT NULL,
    room_id INTEGER NOT NULL,
    warden_id INTEGER NOT NULL,

    filename TEXT NOT NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (hostel_id)
        REFERENCES hostels(id)
        ON DELETE CASCADE,

    FOREIGN KEY (room_id)
        REFERENCES rooms(id)
        ON DELETE CASCADE,

    FOREIGN KEY (warden_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);