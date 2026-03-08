DROP TABLE IF EXISTS bookings;

CREATE TABLE bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    phone TEXT,
    screenshot_filename TEXT,
    seat_id TEXT,
    price INTEGER,
    status TEXT NOT NULL,
    booked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);