from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3, hashlib, os, uuid
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'college_secure_portal_2025_key'
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─── DB HELPERS ──────────────────────────────────────────
def get_db():
    conn = sqlite3.connect('college.db')
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_upload(file_field):
    f = request.files.get(file_field)
    if f and allowed_file(f.filename):
        fname = secure_filename(f"{uuid.uuid4()}_{f.filename}")
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        return fname
    return None

def hours_since(dt_str):
    if not dt_str:
        return 0
    try:
        dt = datetime.fromisoformat(dt_str)
        return round((datetime.now() - dt).total_seconds() / 3600, 1)
    except:
        return 0

# ─── INIT DB ─────────────────────────────────────────────
def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            branch TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            approved INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            approved INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS principals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            branch TEXT NOT NULL,
            room_number TEXT NOT NULL,
            issue_description TEXT NOT NULL,
            photo_path TEXT,
            updated_photo TEXT,
            status TEXT DEFAULT 'Pending',
            teacher_response TEXT,
            date_submitted TEXT DEFAULT CURRENT_TIMESTAMP,
            date_updated TEXT
        );
        CREATE TABLE IF NOT EXISTS infrastructure (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch TEXT NOT NULL,
            room_number TEXT UNIQUE NOT NULL,
            num_benches INTEGER DEFAULT 0,
            num_computers INTEGER DEFAULT 0,
            projector TEXT DEFAULT 'No',
            num_fans INTEGER DEFAULT 0,
            fan_status TEXT DEFAULT 'Working',
            electrical_status TEXT DEFAULT 'Good',
            num_windows INTEGER DEFAULT 0,
            window_condition TEXT DEFAULT 'Good',
            updated_by TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS principal_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL,
            order_text TEXT NOT NULL,
            teacher_response TEXT,
            sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
            responded_at TEXT
        );
    ''')
    # Default principal
    c.execute("INSERT OR IGNORE INTO principals (username,name,password) VALUES (?,?,?)",
              ('principal', 'Dr. S. K. Sharma', hash_password('principal123')))
    conn.commit()
    conn.close()

# ─── AUTH DECORATOR ───────────────────────────────────────
def login_required(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'role' not in session or session['role'] != role:
                flash('Please login to continue.', 'error')
                return redirect(url_for(f'{role}_login'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ════════════════════════════════════════════════════════
# HOME
# ════════════════════════════════════════════════════════
@app.route('/')
def home():
    return render_template('home.html')

# ════════════════════════════════════════════════════════
# STUDENT — REGISTER / LOGIN / DASHBOARD
# ════════════════════════════════════════════════════════
@app.route('/student/register', methods=['GET','POST'])
def student_register():
    if request.method == 'POST':
        sid   = request.form['student_id'].strip().upper()
        name  = request.form['name'].strip()
        branch= request.form['branch'].strip()
        email = request.form['email'].strip().lower()
        pw    = hash_password(request.form['password'])
        conn  = get_db()
        # check unique ID
        exists = conn.execute("SELECT id FROM students WHERE student_id=?", (sid,)).fetchone()
        if exists:
            flash('Student ID already registered. Use a unique ID.', 'error')
            conn.close()
            return render_template('student_register.html')
        try:
            conn.execute("INSERT INTO students (student_id,name,branch,email,password) VALUES (?,?,?,?,?)",
                         (sid, name, branch, email, pw))
            conn.commit()
            flash('Registration successful! Awaiting Principal approval before you can login.', 'success')
            return redirect(url_for('student_login'))
        except sqlite3.IntegrityError:
            flash('Email already exists. Use a different email.', 'error')
        finally:
            conn.close()
    return render_template('student_register.html')

@app.route('/student/login', methods=['GET','POST'])
def student_login():
    if request.method == 'POST':
        sid = request.form['student_id'].strip().upper()
        pw  = hash_password(request.form['password'])
        conn = get_db()
        s = conn.execute("SELECT * FROM students WHERE student_id=? AND password=?", (sid, pw)).fetchone()
        conn.close()
        if s:
            if s['approved']:
                session.update({'role':'student','user_id':s['id'],'name':s['name'],'student_id':sid,'branch':s['branch']})
                return redirect(url_for('student_dashboard'))
            else:
                flash('Your account is pending Principal approval. Please wait.', 'warning')
        else:
            flash('Invalid Student ID or password.', 'error')
    return render_template('student_login.html')

@app.route('/student/dashboard')
@login_required('student')
def student_dashboard():
    conn = get_db()
    complaints = conn.execute(
        "SELECT * FROM complaints WHERE student_id=? ORDER BY date_submitted DESC",
        (session['student_id'],)).fetchall()
    infra = conn.execute("SELECT * FROM infrastructure ORDER BY branch, room_number").fetchall()
    conn.close()
    now = datetime.now()
    complaints_with_hours = []
    for c in complaints:
        submitted = datetime.fromisoformat(c['date_submitted'])
        hrs = round((now - submitted).total_seconds() / 3600, 1)
        overdue = hrs >= 6 and c['status'] == 'Pending'
        complaints_with_hours.append({'c': c, 'hrs': hrs, 'overdue': overdue})
    return render_template('student_dashboard.html',
                           complaints_with_hours=complaints_with_hours, infra=infra)

@app.route('/student/complaint/submit', methods=['GET','POST'])
@login_required('student')
def submit_complaint():
    if request.method == 'POST':
        photo = save_upload('photo')
        conn = get_db()
        conn.execute("""INSERT INTO complaints
            (student_id,student_name,branch,room_number,issue_description,photo_path)
            VALUES (?,?,?,?,?,?)""",
            (session['student_id'], session['name'], request.form['branch'],
             request.form['room_number'], request.form['issue_description'], photo))
        conn.commit()
        conn.close()
        flash('Complaint submitted successfully!', 'success')
        return redirect(url_for('student_dashboard'))
    return render_template('submit_complaint.html')

@app.route('/student/logout')
def student_logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home'))

# ════════════════════════════════════════════════════════
# TEACHER — REGISTER / LOGIN / DASHBOARD
# ════════════════════════════════════════════════════════
@app.route('/teacher/register', methods=['GET','POST'])
def teacher_register():
    if request.method == 'POST':
        tid   = request.form['teacher_id'].strip().upper()
        name  = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        pw    = hash_password(request.form['password'])
        conn  = get_db()
        exists = conn.execute("SELECT id FROM teachers WHERE teacher_id=?", (tid,)).fetchone()
        if exists:
            flash('Teacher ID already registered. Each ID must be unique.', 'error')
            conn.close()
            return render_template('teacher_register.html')
        try:
            conn.execute("INSERT INTO teachers (teacher_id,name,email,password) VALUES (?,?,?,?)",
                         (tid, name, email, pw))
            conn.commit()
            flash('Registration submitted! Awaiting Principal approval.', 'success')
            return redirect(url_for('teacher_login'))
        except sqlite3.IntegrityError:
            flash('Email already exists. Use a different email.', 'error')
        finally:
            conn.close()
    return render_template('teacher_register.html')

@app.route('/teacher/login', methods=['GET','POST'])
def teacher_login():
    if request.method == 'POST':
        tid = request.form['teacher_id'].strip().upper()
        pw  = hash_password(request.form['password'])
        conn = get_db()
        t = conn.execute("SELECT * FROM teachers WHERE teacher_id=? AND password=?", (tid, pw)).fetchone()
        conn.close()
        if t:
            if t['approved']:
                session.update({'role':'teacher','user_id':t['id'],'name':t['name'],'teacher_id':tid})
                return redirect(url_for('teacher_dashboard'))
            else:
                flash('Your account is pending Principal approval.', 'warning')
        else:
            flash('Invalid Teacher ID or password.', 'error')
    return render_template('teacher_login.html')

@app.route('/teacher/dashboard')
@login_required('teacher')
def teacher_dashboard():
    conn = get_db()
    complaints = conn.execute("SELECT * FROM complaints ORDER BY date_submitted DESC").fetchall()
    infra      = conn.execute("SELECT * FROM infrastructure ORDER BY branch, room_number").fetchall()
    orders     = conn.execute("""
        SELECT po.*, c.room_number, c.student_id, c.student_name, c.issue_description
        FROM principal_orders po
        JOIN complaints c ON po.complaint_id = c.id
        WHERE po.teacher_response IS NULL
        ORDER BY po.sent_at DESC""").fetchall()
    responded  = conn.execute("""
        SELECT po.*, c.room_number, c.student_name
        FROM principal_orders po
        JOIN complaints c ON po.complaint_id = c.id
        WHERE po.teacher_response IS NOT NULL
        ORDER BY po.responded_at DESC""").fetchall()
    conn.close()
    now = datetime.now()
    complaints_rich = []
    for c in complaints:
        hrs = hours_since(c['date_submitted'])
        complaints_rich.append({'c':c,'hrs':hrs,'overdue': hrs>=6 and c['status']=='Pending'})
    return render_template('teacher_dashboard.html',
        complaints_rich=complaints_rich, infra=infra, orders=orders, responded=responded,
        branches=['BCA','BBA','BSC','Data Science','BVOC','DSW'])

@app.route('/teacher/complaint/update/<int:cid>', methods=['POST'])
@login_required('teacher')
def update_complaint(cid):
    status   = request.form['status']
    response = request.form.get('teacher_response','').strip()
    updated_photo = save_upload('updated_photo')
    conn = get_db()
    if updated_photo:
        conn.execute("""UPDATE complaints SET status=?,teacher_response=?,date_updated=?,updated_photo=?
                        WHERE id=?""", (status,response,datetime.now().isoformat(),updated_photo,cid))
    else:
        conn.execute("UPDATE complaints SET status=?,teacher_response=?,date_updated=? WHERE id=?",
                     (status,response,datetime.now().isoformat(),cid))
    conn.commit(); conn.close()
    flash('Complaint updated successfully!', 'success')
    return redirect(url_for('teacher_dashboard') + '#tab-complaints')

@app.route('/teacher/order/respond/<int:oid>', methods=['POST'])
@login_required('teacher')
def respond_order(oid):
    resp = request.form['response'].strip()
    conn = get_db()
    conn.execute("UPDATE principal_orders SET teacher_response=?,responded_at=? WHERE id=?",
                 (resp, datetime.now().isoformat(), oid))
    conn.commit(); conn.close()
    flash('Response sent to Principal.', 'success')
    return redirect(url_for('teacher_dashboard') + '#tab-orders')

@app.route('/teacher/infrastructure/add', methods=['POST'])
@login_required('teacher')
def add_infrastructure():
    d = request.form
    conn = get_db()
    try:
        conn.execute("""INSERT INTO infrastructure
            (branch,room_number,num_benches,num_computers,projector,
             num_fans,fan_status,electrical_status,num_windows,window_condition,updated_by,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d['branch'],d['room_number'],d['num_benches'],d['num_computers'],d['projector'],
             d['num_fans'],d['fan_status'],d['electrical_status'],d['num_windows'],
             d['window_condition'],session['name'],datetime.now().isoformat()))
        conn.commit()
        flash('Infrastructure record added successfully!', 'success')
    except sqlite3.IntegrityError:
        flash(f'Room number "{d["room_number"]}" already exists! Room numbers must be unique.', 'error')
    finally:
        conn.close()
    return redirect(url_for('teacher_dashboard') + '#tab-infra')

@app.route('/teacher/infrastructure/update/<int:iid>', methods=['POST'])
@login_required('teacher')
def update_infrastructure(iid):
    d = request.form
    conn = get_db()
    conn.execute("""UPDATE infrastructure SET
        branch=?,num_benches=?,num_computers=?,projector=?,num_fans=?,
        fan_status=?,electrical_status=?,num_windows=?,window_condition=?,
        updated_by=?,updated_at=? WHERE id=?""",
        (d['branch'],d['num_benches'],d['num_computers'],d['projector'],d['num_fans'],
         d['fan_status'],d['electrical_status'],d['num_windows'],d['window_condition'],
         session['name'],datetime.now().isoformat(),iid))
    conn.commit(); conn.close()
    flash('Infrastructure updated!', 'success')
    return redirect(url_for('teacher_dashboard') + '#tab-infra')

@app.route('/teacher/infrastructure/delete/<int:iid>', methods=['POST'])
@login_required('teacher')
def delete_infrastructure(iid):
    conn = get_db()
    conn.execute("DELETE FROM infrastructure WHERE id=?", (iid,))
    conn.commit(); conn.close()
    flash('Infrastructure record deleted.', 'success')
    return redirect(url_for('teacher_dashboard') + '#tab-infra')

# Room search API
@app.route('/api/room/<room_number>')
def room_search(room_number):
    conn = get_db()
    r = conn.execute("SELECT * FROM infrastructure WHERE room_number=?", (room_number.upper(),)).fetchone()
    conn.close()
    if r:
        return jsonify(dict(r))
    return jsonify({'error': 'Room not found'}), 404

@app.route('/teacher/logout')
def teacher_logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home'))

# ════════════════════════════════════════════════════════
# PRINCIPAL — LOGIN / DASHBOARD
# ════════════════════════════════════════════════════════
@app.route('/principal/login', methods=['GET','POST'])
def principal_login():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pw    = hash_password(request.form['password'])
        conn  = get_db()
        p = conn.execute("SELECT * FROM principals WHERE username=? AND password=?", (uname,pw)).fetchone()
        conn.close()
        if p:
            session.update({'role':'principal','user_id':p['id'],'name':p['name']})
            return redirect(url_for('principal_dashboard'))
        flash('Invalid credentials.', 'error')
    return render_template('principal_login.html')

@app.route('/principal/dashboard')
@login_required('principal')
def principal_dashboard():
    conn = get_db()
    six_ago = (datetime.now() - timedelta(hours=6)).isoformat()

    # Overdue = submitted > 6h ago AND (still Pending OR not Resolved AND not updated within 6h)
    overdue = conn.execute("""
        SELECT * FROM complaints
        WHERE date_submitted < ?
          AND (status='Pending'
               OR (status != 'Resolved' AND (date_updated IS NULL OR date_updated < ?)))
        ORDER BY date_submitted ASC""", (six_ago, six_ago)).fetchall()

    all_complaints   = conn.execute("SELECT * FROM complaints ORDER BY date_submitted DESC").fetchall()
    infra            = conn.execute("SELECT * FROM infrastructure ORDER BY branch, room_number").fetchall()
    orders           = conn.execute("""
        SELECT po.*, c.room_number, c.student_id, c.student_name, c.issue_description
        FROM principal_orders po JOIN complaints c ON po.complaint_id=c.id
        ORDER BY po.sent_at DESC""").fetchall()
    pending_students = conn.execute("SELECT * FROM students WHERE approved=0 ORDER BY created_at DESC").fetchall()
    pending_teachers = conn.execute("SELECT * FROM teachers WHERE approved=0 ORDER BY created_at DESC").fetchall()
    all_students     = conn.execute("SELECT * FROM students WHERE approved=1 ORDER BY created_at DESC").fetchall()
    all_teachers     = conn.execute("SELECT * FROM teachers WHERE approved=1 ORDER BY created_at DESC").fetchall()
    conn.close()

    now = datetime.now()
    overdue_rich = []
    for c in overdue:
        hrs = hours_since(c['date_submitted'])
        order_sent = any(o['complaint_id'] == c['id'] for o in orders)
        overdue_rich.append({'c':c,'hrs':hrs,'order_sent':order_sent})

    all_rich = []
    for c in all_complaints:
        hrs = hours_since(c['date_submitted'])
        all_rich.append({'c':c,'hrs':hrs})

    return render_template('principal_dashboard.html',
        overdue_rich=overdue_rich, all_rich=all_rich,
        infra=infra, orders=orders,
        pending_students=pending_students, pending_teachers=pending_teachers,
        all_students=all_students, all_teachers=all_teachers,
        branches=['BCA','BBA','BSC','Data Science','BVOC','DSW'])

@app.route('/principal/send_order/<int:cid>', methods=['POST'])
@login_required('principal')
def send_order(cid):
    conn = get_db()
    conn.execute("INSERT INTO principal_orders (complaint_id,order_text) VALUES (?,?)",
                 (cid, request.form['order_text']))
    conn.commit(); conn.close()
    flash('Order sent to teacher.', 'success')
    return redirect(url_for('principal_dashboard') + '#tab-sla')

@app.route('/principal/approve_student/<int:sid>', methods=['POST'])
@login_required('principal')
def approve_student(sid):
    conn = get_db()
    conn.execute("UPDATE students SET approved=1 WHERE id=?", (sid,))
    conn.commit(); conn.close()
    flash('Student approved successfully.', 'success')
    return redirect(url_for('principal_dashboard') + '#tab-approvals')

@app.route('/principal/reject_student/<int:sid>', methods=['POST'])
@login_required('principal')
def reject_student(sid):
    conn = get_db()
    conn.execute("DELETE FROM students WHERE id=?", (sid,))
    conn.commit(); conn.close()
    flash('Student registration rejected and removed.', 'success')
    return redirect(url_for('principal_dashboard') + '#tab-approvals')

@app.route('/principal/approve_teacher/<int:tid>', methods=['POST'])
@login_required('principal')
def approve_teacher(tid):
    conn = get_db()
    conn.execute("UPDATE teachers SET approved=1 WHERE id=?", (tid,))
    conn.commit(); conn.close()
    flash('Teacher approved successfully.', 'success')
    return redirect(url_for('principal_dashboard') + '#tab-approvals')

@app.route('/principal/reject_teacher/<int:tid>', methods=['POST'])
@login_required('principal')
def reject_teacher(tid):
    conn = get_db()
    conn.execute("DELETE FROM teachers WHERE id=?", (tid,))
    conn.commit(); conn.close()
    flash('Teacher registration rejected and removed.', 'success')
    return redirect(url_for('principal_dashboard') + '#tab-approvals')

@app.route('/principal/logout')
def principal_logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home'))

@app.route('/infrastructure')
def infrastructure():
    conn = get_db()
    infra = conn.execute("SELECT * FROM infrastructure ORDER BY branch, room_number").fetchall()
    conn.close()
    return render_template('infrastructure_public.html', infra=infra)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)