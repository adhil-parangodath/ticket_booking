import os
import uuid
import sqlite3
import pandas as pd
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'AADU_cinema_ultra_secure_2026'
# Admin session securely expires if inactive for 30 minutes
app.permanent_session_lifetime = timedelta(minutes=30)

# --- FOLDER & DATABASE CONFIGURATION ---
# This ensures paths work perfectly on both your laptop and the live server
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
DB_FILE = os.path.join(BASE_DIR, 'booking_data.db')
EXCEL_FILE = os.path.join(BASE_DIR, 'orders.xlsx')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

ADMIN_USER = "adhil"
ADMIN_PASS = "Adhilp1024@ad"

# --- DATABASE MANAGEMENT ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id TEXT UNIQUE,
            ticket_no TEXT UNIQUE,
            name TEXT,
            phone TEXT,
            screenshot TEXT,
            seat_id TEXT,
            price INTEGER,
            status TEXT DEFAULT 'PENDING',
            timestamp DATETIME
        )
    ''')
    conn.commit()
    conn.close()

def sync_to_excel():
    try:
        conn = sqlite3.connect(DB_FILE)
        # We export everything to Excel for your records
        df = pd.read_sql_query("SELECT * FROM bookings ORDER BY timestamp DESC", conn)
        df.to_excel(EXCEL_FILE, index=False)
        conn.close()
    except Exception as e:
        print(f"Excel Sync Error: {e}")

init_db()

# ==========================================
# 1. USER FACING ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/track')
def track_page():
    return render_template('track.html')

@app.route('/submit-payment', methods=['POST'])
def submit_payment():
    """Step 1: Save User Details & Payment Screenshot as INCOMPLETE"""
    try:
        name = request.form.get('name')
        phone_raw = request.form.get('phone', '')
        # Force phone to be only numbers
        phone = "".join(filter(str.isdigit, phone_raw)) 
        
        if 'screenshot' not in request.files:
            return jsonify({"error": "No image file detected."}), 400
            
        file = request.files['screenshot']
        
        if file.filename == '' or not name or len(phone) < 10:
            return jsonify({"error": "Valid name, proper phone number, and screenshot are required."}), 400

        booking_id = str(uuid.uuid4())[:8].upper()
        ticket_no = f"AADU-{datetime.now().strftime('%y%m%d')}-{booking_id}"
        
        safe_filename = secure_filename(file.filename)
        filename = f"{booking_id}_{safe_filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Saved as INCOMPLETE so it doesn't show in Admin yet
        cursor.execute('''
            INSERT INTO bookings (booking_id, ticket_no, name, phone, screenshot, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (booking_id, ticket_no, name, phone, filename, 'INCOMPLETE', datetime.now()))
        conn.commit()
        conn.close()
        
        return jsonify({"booking_id": booking_id, "ticket_no": ticket_no, "name": name})
    
    except Exception as e:
        return jsonify({"error": "Server error processing payment."}), 500

@app.route('/get-occupied-seats')
def get_occupied():
    """Returns seats that are blocked"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT seat_id FROM bookings WHERE status != 'CANCELLED' AND status != 'INCOMPLETE' AND seat_id IS NOT NULL")
    seats = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify({"occupied_seats": seats})

@app.route('/admin/download-excel')
def download_excel():
    """Admin downloads the latest orders.xlsx file"""
    if not session.get('admin_logged_in'): 
        return redirect(url_for('admin_login'))
    
    # Sync one last time to ensure it is 100% up to date
    sync_to_excel()
    
    # Send the file to the browser as a download
    return send_file(EXCEL_FILE, as_attachment=True)

@app.route('/select-seat', methods=['POST'])
def select_seat():
    """Step 2: Attach seat and change status to PENDING"""
    data = request.json
    booking_id = data.get('booking_id')
    seat_id = data.get('seat_id')
    price = data.get('price')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM bookings WHERE seat_id = ? AND status != 'CANCELLED'", (seat_id,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "This seat was just booked by someone else."}), 400

    # Promote from INCOMPLETE to PENDING so Admin can see it
    cursor.execute('''
        UPDATE bookings SET seat_id = ?, price = ?, status = 'PENDING' WHERE booking_id = ?
    ''', (seat_id, price, booking_id))
    
    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Session expired."}), 404

    conn.commit()
    conn.close()
    sync_to_excel()
    return jsonify({"status": "success"})

@app.route('/check-status/<ticket_no>')
def check_status(ticket_no):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, status, seat_id, price FROM bookings WHERE ticket_no = ?", (ticket_no,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return jsonify({
            "found": True, 
            "name": row[0], 
            "status": row[1],
            "seat_id": row[2],
            "price": row[3]
        })
    return jsonify({"found": False})

# ==========================================
# 2. ADMIN FACING ROUTES
# ==========================================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session.permanent = True # Enables the 30-min timeout
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error="Invalid Credentials")
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template('admin.html')

@app.route('/admin/quick-ticket')
def quick_ticket():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template('quick_ticket.html')

@app.route('/admin/get-all')
def admin_get_all():
    if not session.get('admin_logged_in'): return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Exclude INCOMPLETE records from the admin dashboard
    cursor.execute("SELECT * FROM bookings WHERE status != 'INCOMPLETE' ORDER BY timestamp DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/admin/update', methods=['POST'])
def update_status():
    if not session.get('admin_logged_in'): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE bookings SET status = ? WHERE booking_id = ?", (data['status'], data['bid']))
    conn.commit()
    conn.close()
    sync_to_excel()
    return jsonify({"status": "updated"})

@app.route('/admin/update-seat', methods=['POST'])
def update_seat():
    if not session.get('admin_logged_in'): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    booking_id = data.get('bid')
    
    # FIX: Changed 'seat_id' to 'sid' to perfectly match the admin.html file
    new_seat = data.get('sid')
    
    if not new_seat:
        return jsonify({"error": "No seat selected."}), 400
        
    new_seat = new_seat.upper()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM bookings WHERE seat_id = ? AND status != 'CANCELLED' AND booking_id != ?", (new_seat, booking_id))
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": f"Seat {new_seat} is already occupied!"}), 400

    cursor.execute("UPDATE bookings SET seat_id = ? WHERE booking_id = ?", (new_seat, booking_id))
    conn.commit()
    conn.close()
    sync_to_excel()
    return jsonify({"status": "success"})

@app.route('/admin/delete', methods=['POST'])
def delete_booking():
    """Permanently deletes a booking, immediately frees the seat, AND deletes the image file."""
    if not session.get('admin_logged_in'): return jsonify({"error": "Unauthorized"}), 401
    bid = request.json.get('bid')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 1. Find the image filename before deleting the row
    cursor.execute("SELECT screenshot FROM bookings WHERE booking_id = ?", (bid,))
    row = cursor.fetchone()
    
    # 2. If an image exists (and it's not a Walk-in), delete it from the folder
    if row and row[0] and row[0] != 'WALK-IN':
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], row[0])
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Could not delete image file: {e}")
                
    # 3. Now delete the record from the database
    cursor.execute("DELETE FROM bookings WHERE booking_id = ?", (bid,))
    conn.commit()
    conn.close()
    
    sync_to_excel()
    return jsonify({"status": "deleted"})

@app.route('/admin/create-manual-booking', methods=['POST'])
def create_manual_booking():
    if not session.get('admin_logged_in'): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    seat_id = data.get('seat_id')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM bookings WHERE seat_id = ? AND status != 'CANCELLED'", (seat_id,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "Seat already taken."}), 400

    booking_id = str(uuid.uuid4())[:8].upper()
    ticket_no = f"AADU-{datetime.now().strftime('%y%m%d')}-{booking_id}-MANUAL"
    
    cursor.execute('''
        INSERT INTO bookings (booking_id, ticket_no, name, phone, screenshot, seat_id, price, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (booking_id, ticket_no, data.get('name'), data.get('phone'), 'WALK-IN', seat_id, data.get('price'), 'CONFORMED', datetime.now()))
    
    conn.commit()
    conn.close()
    sync_to_excel()
    return jsonify({"status": "success", "ticket_no": ticket_no})

if __name__ == '__main__':
    app.run(debug=True, port=5000)