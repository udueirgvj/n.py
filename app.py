from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3, bcrypt, os
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super-secret-key-change-in-production")
socketio = SocketIO(app, cors_allowed_origins="*")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DB = "social.db"

# ─── Database ───────────────────────────────────────────────
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
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            bio TEXT DEFAULT '',
            avatar TEXT DEFAULT '👤',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_banned INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            hashtags TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read INTEGER DEFAULT 0
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
        """)

init_db()

# ─── Helpers ────────────────────────────────────────────────
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

def add_notification(user_id, content):
    with get_db() as db:
        db.execute("INSERT INTO notifications (user_id, content) VALUES (?, ?)", (user_id, content))

# ─── Auth ────────────────────────────────────────────────────
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            with get_db() as db:
                db.execute("INSERT INTO users (username, email, password) VALUES (?,?,?)", (username, email, hashed))
            return redirect(url_for('login'))
        except:
            return render_template('register.html', error="اسم المستخدم أو البريد مستخدم مسبقاً")
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and bcrypt.checkpw(password.encode(), user['password'].encode()):
            if user['is_banned']:
                return render_template('login.html', error="حسابك موقوف")
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('home'))
        return render_template('login.html', error="بيانات خاطئة")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── Home / Feed ─────────────────────────────────────────────
@app.route('/')
@login_required
def home():
    with get_db() as db:
        posts = db.execute("""
            SELECT p.*, u.username, u.avatar,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
                   (SELECT COUNT(*) FROM comments WHERE post_id=p.id) as comment_count,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id AND user_id=?) as user_liked
            FROM posts p JOIN users u ON p.user_id=u.id
            ORDER BY p.created_at DESC LIMIT 50
        """, (session['user_id'],)).fetchall()
        stories = db.execute("""
            SELECT s.*, u.username, u.avatar FROM stories s
            JOIN users u ON s.user_id=u.id
            ORDER BY s.created_at DESC LIMIT 20
        """).fetchall()
        notif_count = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (session['user_id'],)).fetchone()[0]
        unread_dm = db.execute("SELECT COUNT(*) FROM messages WHERE receiver_id=? AND is_read=0", (session['user_id'],)).fetchone()[0]
    return render_template('home.html', posts=posts, stories=stories, notif_count=notif_count, unread_dm=unread_dm)

# ─── Posts ───────────────────────────────────────────────────
@app.route('/post', methods=['POST'])
@login_required
def create_post():
    content = request.form['content'].strip()
    if content:
        import re
        tags = ' '.join(re.findall(r'#\w+', content))
        with get_db() as db:
            db.execute("INSERT INTO posts (user_id, content, hashtags) VALUES (?,?,?)", (session['user_id'], content, tags))
    return redirect(url_for('home'))

@app.route('/like/<int:post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    with get_db() as db:
        existing = db.execute("SELECT * FROM likes WHERE user_id=? AND post_id=?", (session['user_id'], post_id)).fetchone()
        if existing:
            db.execute("DELETE FROM likes WHERE user_id=? AND post_id=?", (session['user_id'], post_id))
            liked = False
        else:
            db.execute("INSERT INTO likes (user_id, post_id) VALUES (?,?)", (session['user_id'], post_id))
            liked = True
            post = db.execute("SELECT user_id FROM posts WHERE id=?", (post_id,)).fetchone()
            if post and post['user_id'] != session['user_id']:
                add_notification(post['user_id'], f"❤️ {session['username']} أعجب بمنشورك")
        count = db.execute("SELECT COUNT(*) FROM likes WHERE post_id=?", (post_id,)).fetchone()[0]
    return jsonify({"liked": liked, "count": count})

@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def comment(post_id):
    content = request.form['content'].strip()
    if content:
        with get_db() as db:
            db.execute("INSERT INTO comments (user_id, post_id, content) VALUES (?,?,?)", (session['user_id'], post_id, content))
            post = db.execute("SELECT user_id FROM posts WHERE id=?", (post_id,)).fetchone()
            if post and post['user_id'] != session['user_id']:
                add_notification(post['user_id'], f"💬 {session['username']} علّق على منشورك")
    return redirect(url_for('home'))

@app.route('/delete_post/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    with get_db() as db:
        db.execute("DELETE FROM posts WHERE id=? AND user_id=?", (post_id, session['user_id']))
    return redirect(url_for('home'))

# ─── Profile ─────────────────────────────────────────────────
@app.route('/profile/<username>')
@login_required
def profile(username):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user: return "مستخدم غير موجود", 404
        posts = db.execute("""
            SELECT p.*, u.username, u.avatar,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
                   (SELECT COUNT(*) FROM comments WHERE post_id=p.id) as comment_count,
                   (SELECT COUNT(*) FROM likes WHERE post_id=p.id AND user_id=?) as user_liked
            FROM posts p JOIN users u ON p.user_id=u.id
            WHERE p.user_id=? ORDER BY p.created_at DESC
        """, (session['user_id'], user['id'])).fetchall()
        followers = db.execute("SELECT COUNT(*) FROM follows WHERE following_id=?", (user['id'],)).fetchone()[0]
        following = db.execute("SELECT COUNT(*) FROM follows WHERE follower_id=?", (user['id'],)).fetchone()[0]
        is_following = db.execute("SELECT * FROM follows WHERE follower_id=? AND following_id=?", (session['user_id'], user['id'])).fetchone()
    return render_template('profile.html', user=user, posts=posts, followers=followers, following=following, is_following=is_following)

@app.route('/edit_profile', methods=['GET','POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        bio = request.form['bio'].strip()
        avatar = request.form['avatar'].strip()
        with get_db() as db:
            db.execute("UPDATE users SET bio=?, avatar=? WHERE id=?", (bio, avatar, session['user_id']))
        return redirect(url_for('profile', username=session['username']))
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    return render_template('edit_profile.html', user=user)

# ─── Follow ──────────────────────────────────────────────────
@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow(user_id):
    if user_id == session['user_id']: return jsonify({"error": "لا يمكنك متابعة نفسك"})
    with get_db() as db:
        existing = db.execute("SELECT * FROM follows WHERE follower_id=? AND following_id=?", (session['user_id'], user_id)).fetchone()
        if existing:
            db.execute("DELETE FROM follows WHERE follower_id=? AND following_id=?", (session['user_id'], user_id))
            following = False
        else:
            db.execute("INSERT INTO follows (follower_id, following_id) VALUES (?,?)", (session['user_id'], user_id))
            following = True
            add_notification(user_id, f"👤 {session['username']} بدأ متابعتك")
    return jsonify({"following": following})

# ─── Search ──────────────────────────────────────────────────
@app.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    users, posts = [], []
    if q:
        with get_db() as db:
            users = db.execute("SELECT * FROM users WHERE username LIKE ?", (f'%{q}%',)).fetchall()
            posts = db.execute("""
                SELECT p.*, u.username, u.avatar FROM posts p
                JOIN users u ON p.user_id=u.id
                WHERE p.content LIKE ? OR p.hashtags LIKE ?
                ORDER BY p.created_at DESC
            """, (f'%{q}%', f'%{q}%')).fetchall()
    return render_template('search.html', users=users, posts=posts, q=q)

# ─── Notifications ───────────────────────────────────────────
@app.route('/notifications')
@login_required
def notifications():
    with get_db() as db:
        notifs = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC", (session['user_id'],)).fetchall()
        db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session['user_id'],))
    return render_template('notifications.html', notifs=notifs)

# ─── Messages / DM ───────────────────────────────────────────
@app.route('/messages')
@login_required
def messages():
    with get_db() as db:
        convos = db.execute("""
            SELECT DISTINCT u.id, u.username, u.avatar,
                   (SELECT content FROM messages WHERE (sender_id=? AND receiver_id=u.id) OR (sender_id=u.id AND receiver_id=?) ORDER BY created_at DESC LIMIT 1) as last_msg,
                   (SELECT COUNT(*) FROM messages WHERE sender_id=u.id AND receiver_id=? AND is_read=0) as unread
            FROM users u
            WHERE u.id IN (
                SELECT CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END
                FROM messages WHERE sender_id=? OR receiver_id=?
            ) AND u.id != ?
        """, (session['user_id'], session['user_id'], session['user_id'], session['user_id'], session['user_id'], session['user_id'], session['user_id'])).fetchall()
    return render_template('messages.html', convos=convos)

@app.route('/messages/<int:user_id>')
@login_required
def chat(user_id):
    with get_db() as db:
        other = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not other: return "مستخدم غير موجود", 404
        msgs = db.execute("""
            SELECT m.*, u.username, u.avatar FROM messages m
            JOIN users u ON m.sender_id=u.id
            WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
            ORDER BY m.created_at ASC
        """, (session['user_id'], user_id, user_id, session['user_id'])).fetchall()
        db.execute("UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=?", (user_id, session['user_id']))
    return render_template('chat.html', other=other, msgs=msgs)

@app.route('/send_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_message(receiver_id):
    content = request.form['content'].strip()
    if content:
        with get_db() as db:
            db.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?,?,?)", (session['user_id'], receiver_id, content))
    return redirect(url_for('chat', user_id=receiver_id))

# ─── Stories ─────────────────────────────────────────────────
@app.route('/story', methods=['POST'])
@login_required
def create_story():
    content = request.form['content'].strip()
    emoji = request.form.get('emoji', '✨')
    if content:
        with get_db() as db:
            db.execute("INSERT INTO stories (user_id, content, emoji) VALUES (?,?,?)", (session['user_id'], content, emoji))
    return redirect(url_for('home'))

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
        posts = db.execute("SELECT p.*, u.username FROM posts p JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC").fetchall()
        messages = db.execute("SELECT m.*, u.username as sender, r.username as receiver FROM messages m JOIN users u ON m.sender_id=u.id JOIN users r ON m.receiver_id=r.id ORDER BY m.created_at DESC LIMIT 100").fetchall()
        stats = {
            "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "posts": db.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
            "messages": db.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "likes": db.execute("SELECT COUNT(*) FROM likes").fetchone()[0],
        }
    return render_template('admin.html', users=users, posts=posts, messages=messages, stats=stats)

@app.route('/admin/ban/<int:user_id>', methods=['POST'])
@admin_required
def ban_user(user_id):
    with get_db() as db:
        user = db.execute("SELECT is_banned FROM users WHERE id=?", (user_id,)).fetchone()
        new_status = 0 if user['is_banned'] else 1
        db.execute("UPDATE users SET is_banned=? WHERE id=?", (new_status, user_id))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_post/<int:post_id>', methods=['POST'])
@admin_required
def admin_delete_post(post_id):
    with get_db() as db:
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

# ─── SocketIO ────────────────────────────────────────────────
@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)

@socketio.on('send_message')
def handle_message(data):
    emit('receive_message', data, room=data['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
