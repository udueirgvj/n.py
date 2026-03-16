from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room
import sqlite3, bcrypt, os, uuid, base64
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clipn-secret-2024")
socketio = SocketIO(app, cors_allowed_origins="*")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin2024")
DB = "clipn.db"
CLIPN_OWNER_USERNAME = "Clipn"

# ─── Jinja filter ────────────────────────────────────────────
@app.template_filter('format_number')
def format_number(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}K"
    return str(n)

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            bio TEXT DEFAULT '',
            avatar TEXT DEFAULT '😊',
            photo_url TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            dob TEXT DEFAULT '',
            is_private INTEGER DEFAULT 0,
            show_activity INTEGER DEFAULT 1,
            is_banned INTEGER DEFAULT 0,
            ban_until TEXT DEFAULT '',
            is_verified INTEGER DEFAULT 0,
            is_restricted INTEGER DEFAULT 0,
            restrict_label TEXT DEFAULT '',
            two_fa_enabled INTEGER DEFAULT 0,
            two_fa_code TEXT DEFAULT '',
            theme TEXT DEFAULT 'dark',
            age_restriction TEXT DEFAULT 'all',
            notif_likes INTEGER DEFAULT 1,
            notif_follows INTEGER DEFAULT 1,
            notif_visits INTEGER DEFAULT 1,
            notif_reposts INTEGER DEFAULT 1,
            notif_messages INTEGER DEFAULT 1,
            notif_channels INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            device_name TEXT DEFAULT '',
            location TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER DEFAULT NULL,
            content TEXT NOT NULL,
            hashtags TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            UNIQUE(user_id, post_id)
        );
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER NOT NULL,
            following_id INTEGER NOT NULL,
            UNIQUE(follower_id, following_id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS stories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            emoji TEXT DEFAULT '✨',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            avatar TEXT DEFAULT '📡',
            cover_url TEXT DEFAULT '',
            is_verified INTEGER DEFAULT 0,
            base_subscribers INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS channel_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            UNIQUE(user_id, channel_id)
        );
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_from_user INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
    # Create official Clipn channel if not exists
    _create_clipn_channel()

init_db()

def _create_clipn_channel():
    with get_db() as db:
        existing = db.execute("SELECT id FROM channels WHERE username=?", (CLIPN_OWNER_USERNAME,)).fetchone()
        if not existing:
            # Get or create admin user
            admin = db.execute("SELECT id FROM users WHERE username=?", (CLIPN_OWNER_USERNAME,)).fetchone()
            if not admin:
                hashed = bcrypt.hashpw(b"clipn_admin_2024", bcrypt.gensalt()).decode()
                db.execute("INSERT OR IGNORE INTO users (username,display_name,email,password,is_verified) VALUES (?,?,?,?,1)",
                          (CLIPN_OWNER_USERNAME, "Clipn Official", "admin@clipn.com", hashed))
                admin = db.execute("SELECT id FROM users WHERE username=?", (CLIPN_OWNER_USERNAME,)).fetchone()
            if admin:
                db.execute("""INSERT OR IGNORE INTO channels (owner_id,name,username,description,avatar,is_verified,base_subscribers)
                              VALUES (?,?,?,?,?,1,789000)""",
                          (admin['id'], 'Clipn', CLIPN_OWNER_USERNAME,
                           'القناة الرسمية لتطبيق Clipn 🚀', '🌐'))

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

def add_notif(user_id, content, notif_type=None):
    """Add notification respecting user settings"""
    if notif_type:
        with get_db() as db:
            user = db.execute(f"SELECT {notif_type} FROM users WHERE id=?", (user_id,)).fetchone()
            if user and not user[notif_type]:
                return  # User disabled this notification type
    with get_db() as db:
        db.execute("INSERT INTO notifications (user_id,content) VALUES (?,?)", (user_id, content))

def get_user_context():
    if 'user_id' not in session: return {}
    with get_db() as db:
        notif_count = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (session['user_id'],)).fetchone()[0]
        unread_dm = db.execute("SELECT COUNT(*) FROM messages WHERE receiver_id=? AND is_read=0", (session['user_id'],)).fetchone()[0]
    return {'notif_count': notif_count, 'unread_dm': unread_dm}

def save_photo(file_data, filename):
    """Save photo as base64 data URL"""
    if not file_data or file_data.filename == '':
        return None
    data = file_data.read()
    if not data: return None
    ext = file_data.filename.rsplit('.', 1)[-1].lower()
    mime = {'jpg':'jpeg','jpeg':'jpeg','png':'png','gif':'gif','webp':'webp'}.get(ext,'jpeg')
    b64 = base64.b64encode(data).decode()
    return f"data:image/{mime};base64,{b64}"

# ─── Auth ────────────────────────────────────────────────────
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip().lstrip('@')
        display_name = request.form.get('display_name','').strip()
        email = request.form['email'].strip()
        password = request.form['password']
        dob_day = request.form.get('dob_day','1')
        dob_month = request.form.get('dob_month','يناير')
        dob_year = request.form.get('dob_year','2000')
        dob = f"{dob_day} {dob_month} {dob_year}"
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            with get_db() as db:
                db.execute("INSERT INTO users (username,display_name,email,password,dob) VALUES (?,?,?,?,?)",
                          (username, display_name or username, email, hashed, dob))
            return redirect(url_for('login'))
        except:
            return render_template('register.html', error="اسم المستخدم أو البريد مستخدم مسبقاً")
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        two_fa = request.form.get('two_fa_code','').strip()
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and bcrypt.checkpw(password.encode(), user['password'].encode()):
            if user['is_banned']:
                msg = f"حسابك موقوف حتى {user['ban_until']}" if user['ban_until'] else "حسابك موقوف"
                return render_template('login.html', error=msg)
            if user['two_fa_enabled'] and two_fa != user['two_fa_code']:
                return render_template('login.html', error="رمز التحقق بخطوتين غير صحيح", show_2fa=True)
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['display_name'] = user['display_name']
            session['avatar'] = user['avatar']
            session['photo_url'] = user['photo_url']
            session['theme'] = user['theme']
            sess_id = str(uuid.uuid4())
            session['session_id'] = sess_id
            ua = request.headers.get('User-Agent','')
            device = 'موبايل' if 'Mobile' in ua else 'كمبيوتر'
            with get_db() as db:
                db.execute("INSERT OR IGNORE INTO sessions (id,user_id,device_name) VALUES (?,?,?)",
                          (sess_id, user['id'], device))
            return redirect(url_for('home'))
        return render_template('login.html', error="بيانات خاطئة")
    return render_template('login.html')

@app.route('/logout')
def logout():
    sess_id = session.get('session_id')
    if sess_id:
        with get_db() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (sess_id,))
    session.clear()
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET','POST'])
def forgot_password():
    msg = None
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user:
            parts = email.split('@')
            masked = parts[0][:2] + '***' + '@' + parts[1]
            msg = f"تم إرسال كلمة المرور إلى {masked}"
        else:
            msg = "البريد غير موجود"
    return render_template('forgot_password.html', msg=msg)

# ─── Home ────────────────────────────────────────────────────
@app.route('/')
@login_required
def home():
    with get_db() as db:
        posts = db.execute("""
            SELECT p.*, u.username, u.display_name, u.avatar, u.photo_url, u.is_verified, u.is_restricted, u.restrict_label,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
                   (SELECT COUNT(*) FROM comments WHERE post_id=p.id) as comment_count,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id AND user_id=?) as user_liked
            FROM posts p JOIN users u ON p.user_id=u.id
            WHERE p.channel_id IS NULL
            ORDER BY p.created_at DESC LIMIT 50
        """, (session['user_id'],)).fetchall()
        stories = db.execute("""
            SELECT s.*, u.username, u.avatar, u.photo_url FROM stories s
            JOIN users u ON s.user_id=u.id ORDER BY s.created_at DESC LIMIT 20
        """).fetchall()
    ctx = get_user_context()
    return render_template('home.html', posts=posts, stories=stories, **ctx)

# ─── Posts ───────────────────────────────────────────────────
@app.route('/post', methods=['POST'])
@login_required
def create_post():
    content = request.form['content'].strip()
    if content:
        import re
        tags = ' '.join(re.findall(r'#\w+', content))
        with get_db() as db:
            db.execute("INSERT INTO posts (user_id,content,hashtags) VALUES (?,?,?)", (session['user_id'], content, tags))
    return redirect(url_for('home'))

@app.route('/like/<int:post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    with get_db() as db:
        ex = db.execute("SELECT * FROM likes WHERE user_id=? AND post_id=?", (session['user_id'], post_id)).fetchone()
        if ex:
            db.execute("DELETE FROM likes WHERE user_id=? AND post_id=?", (session['user_id'], post_id))
            liked = False
        else:
            db.execute("INSERT INTO likes (user_id,post_id) VALUES (?,?)", (session['user_id'], post_id))
            liked = True
            p = db.execute("SELECT user_id FROM posts WHERE id=?", (post_id,)).fetchone()
            if p and p['user_id'] != session['user_id']:
                add_notif(p['user_id'], f"❤️ {session['username']} أعجب بمنشورك", 'notif_likes')
        count = db.execute("SELECT COUNT(*) FROM likes WHERE post_id=?", (post_id,)).fetchone()[0]
    return jsonify({"liked": liked, "count": count})

@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def comment(post_id):
    content = request.form['content'].strip()
    if content:
        with get_db() as db:
            db.execute("INSERT INTO comments (user_id,post_id,content) VALUES (?,?,?)", (session['user_id'], post_id, content))
            p = db.execute("SELECT user_id FROM posts WHERE id=?", (post_id,)).fetchone()
            if p and p['user_id'] != session['user_id']:
                add_notif(p['user_id'], f"💬 {session['username']} علّق على منشورك", 'notif_likes')
    return redirect(url_for('home'))

@app.route('/delete_post/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    with get_db() as db:
        db.execute("DELETE FROM posts WHERE id=? AND user_id=?", (post_id, session['user_id']))
    return redirect(url_for('home'))

@app.route('/story', methods=['POST'])
@login_required
def create_story():
    content = request.form['content'].strip()
    emoji = request.form.get('emoji','✨')
    if content:
        with get_db() as db:
            db.execute("INSERT INTO stories (user_id,content,emoji) VALUES (?,?,?)", (session['user_id'], content, emoji))
    return redirect(url_for('home'))

# ─── Profile ─────────────────────────────────────────────────
@app.route('/profile/<username>')
@login_required
def profile(username):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user: return "مستخدم غير موجود", 404
        posts = db.execute("""
            SELECT p.*, u.username, u.display_name, u.avatar, u.photo_url, u.is_verified, u.is_restricted,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
                   (SELECT COUNT(*) FROM comments WHERE post_id=p.id) as comment_count,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id AND user_id=?) as user_liked
            FROM posts p JOIN users u ON p.user_id=u.id
            WHERE p.user_id=? AND p.channel_id IS NULL ORDER BY p.created_at DESC
        """, (session['user_id'], user['id'])).fetchall()
        followers = db.execute("SELECT COUNT(*) FROM follows WHERE following_id=?", (user['id'],)).fetchone()[0]
        following_count = db.execute("SELECT COUNT(*) FROM follows WHERE follower_id=?", (user['id'],)).fetchone()[0]
        is_following = db.execute("SELECT * FROM follows WHERE follower_id=? AND following_id=?", (session['user_id'], user['id'])).fetchone()
        channels = db.execute("SELECT * FROM channels WHERE owner_id=?", (user['id'],)).fetchall()
    ctx = get_user_context()
    return render_template('profile.html', user=user, posts=posts, followers=followers,
                          following=following_count, is_following=is_following, channels=channels, **ctx)

@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow(user_id):
    if user_id == session['user_id']: return jsonify({"error": "لا يمكنك متابعة نفسك"})
    with get_db() as db:
        ex = db.execute("SELECT * FROM follows WHERE follower_id=? AND following_id=?", (session['user_id'], user_id)).fetchone()
        if ex:
            db.execute("DELETE FROM follows WHERE follower_id=? AND following_id=?", (session['user_id'], user_id))
            following = False
        else:
            db.execute("INSERT INTO follows (follower_id,following_id) VALUES (?,?)", (session['user_id'], user_id))
            following = True
            add_notif(user_id, f"👤 {session['username']} بدأ متابعتك", 'notif_follows')
    return jsonify({"following": following})

# ─── Search ──────────────────────────────────────────────────
@app.route('/search')
@login_required
def search():
    q = request.args.get('q','').strip()
    users, posts, channels = [], [], []
    if q:
        with get_db() as db:
            users = db.execute("SELECT * FROM users WHERE username LIKE ? OR display_name LIKE ?", (f'%{q}%',f'%{q}%')).fetchall()
            posts = db.execute("""
                SELECT p.*, u.username, u.display_name, u.avatar, u.photo_url FROM posts p JOIN users u ON p.user_id=u.id
                WHERE (p.content LIKE ? OR p.hashtags LIKE ?) AND p.channel_id IS NULL ORDER BY p.created_at DESC
            """, (f'%{q}%',f'%{q}%')).fetchall()
            channels = db.execute("SELECT * FROM channels WHERE name LIKE ? OR username LIKE ?", (f'%{q}%',f'%{q}%')).fetchall()
    ctx = get_user_context()
    return render_template('search.html', users=users, posts=posts, channels=channels, q=q, **ctx)

# ─── Notifications ───────────────────────────────────────────
@app.route('/notifications')
@login_required
def notifications():
    with get_db() as db:
        notifs = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC", (session['user_id'],)).fetchall()
        db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session['user_id'],))
    ctx = get_user_context()
    return render_template('notifications.html', notifs=notifs, **ctx)

# ─── Messages ────────────────────────────────────────────────
@app.route('/messages')
@login_required
def messages():
    with get_db() as db:
        convos = db.execute("""
            SELECT DISTINCT u.id, u.username, u.display_name, u.avatar, u.photo_url,
                   (SELECT content FROM messages WHERE (sender_id=? AND receiver_id=u.id) OR (sender_id=u.id AND receiver_id=?) ORDER BY created_at DESC LIMIT 1) as last_msg,
                   (SELECT COUNT(*) FROM messages WHERE sender_id=u.id AND receiver_id=? AND is_read=0) as unread
            FROM users u WHERE u.id IN (
                SELECT CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END
                FROM messages WHERE sender_id=? OR receiver_id=?
            ) AND u.id != ?
        """, (session['user_id'],)*7).fetchall()
    ctx = get_user_context()
    return render_template('messages.html', convos=convos, **ctx)

@app.route('/messages/<int:user_id>')
@login_required
def chat(user_id):
    with get_db() as db:
        other = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not other: return "مستخدم غير موجود", 404
        msgs = db.execute("""
            SELECT m.*, u.username, u.display_name, u.avatar, u.photo_url FROM messages m
            JOIN users u ON m.sender_id=u.id
            WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
            ORDER BY m.created_at ASC
        """, (session['user_id'], user_id, user_id, session['user_id'])).fetchall()
        db.execute("UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=?", (user_id, session['user_id']))
    ctx = get_user_context()
    return render_template('chat.html', other=other, msgs=msgs, **ctx)

@app.route('/send_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_message(receiver_id):
    content = request.form['content'].strip()
    if content:
        with get_db() as db:
            db.execute("INSERT INTO messages (sender_id,receiver_id,content) VALUES (?,?,?)", (session['user_id'], receiver_id, content))
        add_notif(receiver_id, f"💬 رسالة جديدة من {session['username']}", 'notif_messages')
    return redirect(url_for('chat', user_id=receiver_id))

# ─── Settings ────────────────────────────────────────────────
@app.route('/settings')
@login_required
def settings():
    ctx = get_user_context()
    return render_template('settings.html', **ctx)

@app.route('/settings/profile', methods=['GET','POST'])
@login_required
def settings_profile():
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    success = error = None
    if request.method == 'POST':
        display_name = request.form.get('display_name','').strip()
        bio = request.form.get('bio','').strip()
        avatar = request.form.get('avatar','😊').strip()
        new_username = request.form.get('username_edit','').strip().lstrip('@')
        photo_url = user['photo_url']
        # Handle photo upload
        if 'photo' in request.files:
            photo = request.files['photo']
            saved = save_photo(photo, f"user_{session['user_id']}")
            if saved:
                photo_url = saved
        try:
            final_username = new_username if new_username else user['username']
            with get_db() as db:
                db.execute("UPDATE users SET display_name=?,bio=?,avatar=?,username=?,photo_url=? WHERE id=?",
                          (display_name, bio, avatar, final_username, photo_url, session['user_id']))
            session['display_name'] = display_name
            session['avatar'] = avatar
            session['photo_url'] = photo_url
            if new_username: session['username'] = new_username
            success = "تم حفظ التغييرات بنجاح ✅"
            with get_db() as db:
                user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
        except Exception as e:
            error = "اسم المستخدم مستخدم مسبقاً"
    ctx = get_user_context()
    return render_template('settings_profile.html', user=user, success=success, error=error, **ctx)

@app.route('/settings/privacy', methods=['GET'])
@login_required
def settings_privacy():
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    ctx = get_user_context()
    return render_template('settings_privacy.html', user=user, **ctx)

@app.route('/settings/privacy/toggle', methods=['POST'])
@login_required
def toggle_private():
    with get_db() as db:
        user = db.execute("SELECT is_private FROM users WHERE id=?", (session['user_id'],)).fetchone()
        db.execute("UPDATE users SET is_private=? WHERE id=?", (0 if user['is_private'] else 1, session['user_id']))
    return redirect(url_for('settings_privacy'))

@app.route('/settings/privacy/activity', methods=['POST'])
@login_required
def toggle_activity():
    with get_db() as db:
        user = db.execute("SELECT show_activity FROM users WHERE id=?", (session['user_id'],)).fetchone()
        db.execute("UPDATE users SET show_activity=? WHERE id=?", (0 if user['show_activity'] else 1, session['user_id']))
    return redirect(url_for('settings_privacy'))

@app.route('/settings/security')
@login_required
def settings_security():
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
        sessions_list = db.execute("SELECT * FROM sessions WHERE user_id=? ORDER BY created_at DESC", (session['user_id'],)).fetchall()
    ctx = get_user_context()
    return render_template('settings_security.html', user=user, sessions=sessions_list, current_session_id=session.get('session_id'), **ctx)

@app.route('/settings/security/logout-session/<sess_id>', methods=['POST'])
@login_required
def logout_session(sess_id):
    with get_db() as db:
        db.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (sess_id, session['user_id']))
    return redirect(url_for('settings_security'))

@app.route('/settings/security/2fa', methods=['GET'])
@login_required
def settings_2fa():
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    ctx = get_user_context()
    return render_template('settings_2fa.html', user=user, **ctx)

@app.route('/settings/security/2fa/enable', methods=['POST'])
@login_required
def enable_2fa():
    code = request.form['two_fa_code'].strip()
    confirm = request.form['two_fa_confirm'].strip()
    if code != confirm:
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
        return render_template('settings_2fa.html', user=user, error="الرمزان غير متطابقان", **get_user_context())
    with get_db() as db:
        db.execute("UPDATE users SET two_fa_enabled=1,two_fa_code=? WHERE id=?", (code, session['user_id']))
    return redirect(url_for('settings_2fa'))

@app.route('/settings/security/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    password = request.form['password']
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    if bcrypt.checkpw(password.encode(), user['password'].encode()):
        with get_db() as db:
            db.execute("UPDATE users SET two_fa_enabled=0,two_fa_code='' WHERE id=?", (session['user_id'],))
    return redirect(url_for('settings_2fa'))

@app.route('/settings/appearance', methods=['GET','POST'])
@login_required
def settings_appearance():
    if request.method == 'POST':
        theme = request.form.get('theme','dark')
        with get_db() as db:
            db.execute("UPDATE users SET theme=? WHERE id=?", (theme, session['user_id']))
        session['theme'] = theme
        return redirect(url_for('settings_appearance'))
    ctx = get_user_context()
    return render_template('settings_appearance.html', **ctx)

@app.route('/settings/notifications', methods=['GET','POST'])
@login_required
def settings_notifications():
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    if request.method == 'POST':
        fields = ['notif_likes','notif_follows','notif_visits','notif_reposts','notif_messages','notif_channels']
        for f in fields:
            val = 1 if f in request.form else 0
            with get_db() as db:
                db.execute(f"UPDATE users SET {f}=? WHERE id=?", (val, session['user_id']))
        return redirect(url_for('settings_notifications'))
    ctx = get_user_context()
    return render_template('settings_notifications.html', user=user, **ctx)

@app.route('/settings/audience', methods=['GET','POST'])
@login_required
def settings_audience():
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    if request.method == 'POST':
        restriction = request.form.get('age_restriction','all')
        with get_db() as db:
            db.execute("UPDATE users SET age_restriction=? WHERE id=?", (restriction, session['user_id']))
        return redirect(url_for('settings_audience'))
    ctx = get_user_context()
    return render_template('settings_audience.html', user=user, **ctx)

@app.route('/settings/share-profile')
@login_required
def share_profile():
    link = f"https://n-py.onrender.com/profile/{session['username']}"
    ctx = get_user_context()
    return render_template('share_profile.html', link=link, **ctx)

# ─── Help ────────────────────────────────────────────────────
@app.route('/help')
@login_required
def help_center():
    return render_template('help.html', **get_user_context())

@app.route('/help/account-info')
@login_required
def help_account_info():
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    return render_template('help_account_info.html', user=user, **get_user_context())

@app.route('/help/hacked', methods=['GET','POST'])
@login_required
def help_hacked():
    success = None
    if request.method == 'POST':
        msg = request.form.get('message','').strip()
        if msg:
            with get_db() as db:
                db.execute("INSERT INTO support_messages (user_id,content) VALUES (?,?)", (session['user_id'], msg))
            success = "تم إرسال رسالتك للدعم الفني بنجاح ✅"
    return render_template('help_hacked.html', success=success, **get_user_context())

@app.route('/help/security')
@login_required
def help_security():
    return redirect(url_for('settings_security'))

@app.route('/privacy-center')
@login_required
def privacy_center():
    return render_template('privacy_center.html', **get_user_context())

@app.route('/support')
@login_required
def support():
    return render_template('support.html', **get_user_context())

# ─── Channels ────────────────────────────────────────────────
@app.route('/channels')
@login_required
def channels():
    with get_db() as db:
        chans = db.execute("""
            SELECT c.*,
                   c.base_subscribers + (SELECT COUNT(*) FROM channel_subscriptions WHERE channel_id=c.id) as subscribers
            FROM channels c ORDER BY subscribers DESC
        """).fetchall()
    return render_template('channels.html', channels=chans, **get_user_context())

@app.route('/channel/<int:channel_id>')
@login_required
def view_channel(channel_id):
    with get_db() as db:
        channel = db.execute("""
            SELECT c.*,
                   c.base_subscribers + (SELECT COUNT(*) FROM channel_subscriptions WHERE channel_id=c.id) as subscribers
            FROM channels c WHERE c.id=?
        """, (channel_id,)).fetchone()
        if not channel: return "قناة غير موجودة", 404
        posts = db.execute("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id AND user_id=?) as user_liked
            FROM posts p WHERE p.channel_id=? ORDER BY p.created_at DESC
        """, (session['user_id'], channel_id)).fetchall()
        is_subscribed = db.execute("SELECT * FROM channel_subscriptions WHERE user_id=? AND channel_id=?",
                                   (session['user_id'], channel_id)).fetchone()
    return render_template('channel_view.html', channel=channel, posts=posts, is_subscribed=is_subscribed, **get_user_context())

@app.route('/channel/<int:channel_id>/subscribe', methods=['POST'])
@login_required
def subscribe_channel(channel_id):
    with get_db() as db:
        try:
            db.execute("INSERT INTO channel_subscriptions (user_id,channel_id) VALUES (?,?)", (session['user_id'], channel_id))
        except: pass
    return redirect(url_for('view_channel', channel_id=channel_id))

@app.route('/channel/<int:channel_id>/unsubscribe', methods=['POST'])
@login_required
def unsubscribe_channel(channel_id):
    with get_db() as db:
        db.execute("DELETE FROM channel_subscriptions WHERE user_id=? AND channel_id=?", (session['user_id'], channel_id))
    return redirect(url_for('view_channel', channel_id=channel_id))

@app.route('/channel/<int:channel_id>/post', methods=['POST'])
@login_required
def post_in_channel(channel_id):
    with get_db() as db:
        channel = db.execute("SELECT * FROM channels WHERE id=? AND owner_id=?", (channel_id, session['user_id'])).fetchone()
        if not channel: return "غير مصرح", 403
        content = request.form['content'].strip()
        if content:
            db.execute("INSERT INTO posts (user_id,channel_id,content) VALUES (?,?,?)", (session['user_id'], channel_id, content))
    return redirect(url_for('view_channel', channel_id=channel_id))

@app.route('/channel/create', methods=['GET','POST'])
@login_required
def create_channel():
    if request.method == 'POST':
        name = request.form['name'].strip()
        username = request.form['username'].strip().lstrip('@')
        desc = request.form.get('description','').strip()
        avatar = request.form.get('avatar','📡').strip()
        cover_url = ''
        if 'cover' in request.files:
            saved = save_photo(request.files['cover'], f"ch_{username}")
            if saved: cover_url = saved
        try:
            with get_db() as db:
                db.execute("INSERT INTO channels (owner_id,name,username,description,avatar,cover_url) VALUES (?,?,?,?,?,?)",
                          (session['user_id'], name, username, desc, avatar, cover_url))
            return redirect(url_for('channels'))
        except:
            return render_template('create_channel.html', error="اسم المستخدم مستخدم مسبقاً", **get_user_context())
    return render_template('create_channel.html', **get_user_context())

# ─── Admin ───────────────────────────────────────────────────
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error="كلمة مرور خاطئة")
    return render_template('admin_login.html')

@app.route('/admin')
@admin_required
def admin_dashboard():
    with get_db() as db:
        users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        posts = db.execute("SELECT p.*,u.username FROM posts p JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC").fetchall()
        msgs = db.execute("SELECT m.*,u.username as sender,r.username as receiver FROM messages m JOIN users u ON m.sender_id=u.id JOIN users r ON m.receiver_id=r.id ORDER BY m.created_at DESC LIMIT 100").fetchall()
        support_msgs = db.execute("SELECT s.*,u.username FROM support_messages s JOIN users u ON s.user_id=u.id ORDER BY s.created_at DESC").fetchall()
        stats = {
            'users': db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            'posts': db.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            'messages': db.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            'active': db.execute("SELECT COUNT(DISTINCT user_id) FROM sessions").fetchone()[0],
        }
    return render_template('admin.html', users=users, posts=posts, messages=msgs, support_msgs=support_msgs, stats=stats)

@app.route('/admin/user/<int:user_id>')
@admin_required
def admin_view_user(user_id):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        posts = db.execute("SELECT * FROM posts WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        user_msgs = db.execute("SELECT m.*,u.username as receiver FROM messages m JOIN users u ON m.receiver_id=u.id WHERE m.sender_id=? ORDER BY m.created_at DESC LIMIT 50", (user_id,)).fetchall()
    return render_template('admin_user.html', user=user, posts=posts, user_msgs=user_msgs)

@app.route('/admin/ban/<int:user_id>', methods=['POST'])
@admin_required
def admin_ban(user_id):
    ban_until = request.form.get('ban_until','')
    with get_db() as db:
        user = db.execute("SELECT is_banned FROM users WHERE id=?", (user_id,)).fetchone()
        new_status = 0 if user['is_banned'] else 1
        db.execute("UPDATE users SET is_banned=?,ban_until=? WHERE id=?", (new_status, ban_until if new_status else '', user_id))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    with get_db() as db:
        db.execute("DELETE FROM users WHERE id=?", (user_id,))
        db.execute("DELETE FROM posts WHERE user_id=?", (user_id,))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_post/<int:post_id>', methods=['POST'])
@admin_required
def admin_delete_post(post_id):
    with get_db() as db:
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/restrict/<int:user_id>', methods=['POST'])
@admin_required
def admin_restrict(user_id):
    label = request.form.get('label','مقيّد')
    with get_db() as db:
        user = db.execute("SELECT is_restricted FROM users WHERE id=?", (user_id,)).fetchone()
        new = 0 if user['is_restricted'] else 1
        db.execute("UPDATE users SET is_restricted=?,restrict_label=? WHERE id=?", (new, label if new else '', user_id))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/verify/<int:user_id>', methods=['POST'])
@admin_required
def admin_verify(user_id):
    with get_db() as db:
        user = db.execute("SELECT is_verified FROM users WHERE id=?", (user_id,)).fetchone()
        db.execute("UPDATE users SET is_verified=? WHERE id=?", (0 if user['is_verified'] else 1, user_id))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/broadcast', methods=['POST'])
@admin_required
def admin_broadcast():
    content = request.form.get('content','').strip()
    if content:
        with get_db() as db:
            users = db.execute("SELECT id FROM users").fetchall()
            for u in users:
                db.execute("INSERT INTO notifications (user_id,content) VALUES (?,?)", (u['id'], f"📢 {content}"))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/channel_post/<int:channel_id>', methods=['POST'])
@admin_required
def admin_channel_post(channel_id):
    content = request.form.get('content','').strip()
    if content:
        with get_db() as db:
            channel = db.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
            if channel:
                db.execute("INSERT INTO posts (user_id,channel_id,content) VALUES (?,?,?)",
                          (channel['owner_id'], channel_id, content))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

@socketio.on('join')
def on_join(data):
    join_room(data['room'])

@socketio.on('send_message')
def handle_message(data):
    emit('receive_message', data, room=data['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)

