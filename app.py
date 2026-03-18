from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room
import bcrypt, os, uuid, base64, requests as http
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clipn-secret-2024")
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin2024")

# â”€â”€â”€ Firebase Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FB_URL = "https://tttrt-b8c5a-default-rtdb.asia-southeast1.firebasedatabase.app"
FB_KEY = os.environ.get("FIREBASE_SECRET", "")  # Database secret key

def _fb_params():
    return {"auth": FB_KEY} if FB_KEY else {}

def fb_get(path):
    try:
        r = http.get(f"{FB_URL}/{path}.json", params=_fb_params(), timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

def fb_set(path, data):
    try:
        r = http.put(f"{FB_URL}/{path}.json", json=data, params=_fb_params(), timeout=10)
        return r.json()
    except: return None

def fb_push(path, data):
    try:
        r = http.post(f"{FB_URL}/{path}.json", json=data, params=_fb_params(), timeout=10)
        return r.json()
    except: return None

def fb_update(path, data):
    try:
        r = http.patch(f"{FB_URL}/{path}.json", json=data, params=_fb_params(), timeout=10)
        return r.json()
    except: return None

def fb_delete(path):
    try:
        http.delete(f"{FB_URL}/{path}.json", params=_fb_params(), timeout=10)
    except: pass

def fb_query(path, order_by=None, limit=50):
    try:
        r = http.get(f"{FB_URL}/{path}.json", params=_fb_params(), timeout=10)
        data = r.json() if r.status_code == 200 else None
        if not data or not isinstance(data, dict): return []
        items = []
        for k, v in data.items():
            if isinstance(v, dict):
                v['_id'] = k
                items.append(v)
        return items
    except: return []

# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.template_filter('format_number')
def format_number(n):
    try:
        n = int(n)
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000: return f"{n/1_000:.1f}K"
        return str(n)
    except: return str(n)

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

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

def get_user_by_username(username):
    users = fb_query('users')
    for u in users:
        if u.get('username') == username:
            return u
    return None

def get_user_by_id(uid):
    data = fb_get(f'users/{uid}')
    if data:
        data['_id'] = uid
    return data

def add_notif(user_id, content, notif_type=None):
    user = get_user_by_id(user_id)
    if notif_type and user:
        if not user.get(notif_type, True):
            return
    fb_push(f'notifications/{user_id}', {
        'content': content,
        'is_read': False,
        'created_at': now()
    })

def get_user_context():
    if 'user_id' not in session: return {}
    notifs = fb_get(f'notifications/{session["user_id"]}') or {}
    notif_count = sum(1 for v in notifs.values() if isinstance(v, dict) and not v.get('is_read')) if isinstance(notifs, dict) else 0
    msgs = fb_get(f'messages') or {}
    unread_dm = 0
    if isinstance(msgs, dict):
        for conv_id, conv in msgs.items():
            if isinstance(conv, dict):
                for msg_id, msg in conv.items():
                    if isinstance(msg, dict) and msg.get('receiver_id') == session['user_id'] and not msg.get('is_read'):
                        unread_dm += 1
    return {'notif_count': notif_count, 'unread_dm': unread_dm}

def save_photo(file_data):
    if not file_data or file_data.filename == '':
        return None
    try:
        data = file_data.read(1024 * 1024)  # 1MB max
        if not data or len(data) < 100: return None
        ext = file_data.filename.rsplit('.', 1)[-1].lower() if '.' in file_data.filename else 'jpg'
        mime = {'jpg':'jpeg','jpeg':'jpeg','png':'png','gif':'gif','webp':'webp'}.get(ext,'jpeg')
        b64 = base64.b64encode(data).decode()
        return f"data:image/{mime};base64,{b64}"
    except: return None

def ensure_clipn_channel():
    channels = fb_query('channels')
    for ch in channels:
        if ch.get('username') == 'Clipn':
            return
    # Create Clipn official channel
    fb_push('channels', {
        'name': 'Clipn',
        'username': 'Clipn',
        'description': 'Ø§Ù„Ù‚Ù†Ø§Ø© Ø§Ù„Ø±Ø³Ù…ÙŠØ© Ù„ØªØ·Ø¨ÙŠÙ‚ Clipn ðŸš€',
        'avatar': 'ðŸŒ',
        'cover_url': '',
        'is_verified': True,
        'base_subscribers': 789000,
        'owner_id': 'admin',
        'created_at': now()
    })

# Initialize Clipn channel on startup
try:
    ensure_clipn_channel()
except: pass

# â”€â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip().lstrip('@')
        display_name = request.form.get('display_name','').strip()
        email = request.form['email'].strip()
        password = request.form['password']
        dob = f"{request.form.get('dob_day','1')} {request.form.get('dob_month','ÙŠÙ†Ø§ÙŠØ±')} {request.form.get('dob_year','2000')}"

        # Check username exists
        existing = get_user_by_username(username)
        if existing:
            return render_template('register.html', error="Ø§Ø³Ù… Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ù…Ø³ØªØ®Ø¯Ù… Ù…Ø³Ø¨Ù‚Ø§Ù‹")

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user_id = str(uuid.uuid4())
        fb_set(f'users/{user_id}', {
            'username': username,
            'display_name': display_name or username,
            'email': email,
            'password': hashed,
            'bio': '',
            'avatar': 'ðŸ˜Š',
            'photo_url': '',
            'dob': dob,
            'is_private': False,
            'show_activity': True,
            'is_banned': False,
            'ban_until': '',
            'is_verified': False,
            'is_restricted': False,
            'restrict_label': '',
            'two_fa_enabled': False,
            'two_fa_code': '',
            'theme': 'dark',
            'notif_likes': True,
            'notif_follows': True,
            'notif_visits': True,
            'notif_reposts': True,
            'notif_messages': True,
            'notif_channels': True,
            'created_at': now()
        })
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        two_fa = request.form.get('two_fa_code','').strip()

        user = get_user_by_username(username)
        if not user:
            return render_template('login.html', error="Ø¨ÙŠØ§Ù†Ø§Øª Ø®Ø§Ø·Ø¦Ø©")

        if not bcrypt.checkpw(password.encode(), user['password'].encode()):
            return render_template('login.html', error="Ø¨ÙŠØ§Ù†Ø§Øª Ø®Ø§Ø·Ø¦Ø©")

        if user.get('is_banned'):
            msg = f"Ø­Ø³Ø§Ø¨Ùƒ Ù…ÙˆÙ‚ÙˆÙ Ø­ØªÙ‰ {user.get('ban_until','')}" if user.get('ban_until') else "Ø­Ø³Ø§Ø¨Ùƒ Ù…ÙˆÙ‚ÙˆÙ"
            return render_template('login.html', error=msg)

        if user.get('two_fa_enabled') and two_fa != user.get('two_fa_code',''):
            return render_template('login.html', error="Ø±Ù…Ø² Ø§Ù„ØªØ­Ù‚Ù‚ Ø¨Ø®Ø·ÙˆØªÙŠÙ† ØºÙŠØ± ØµØ­ÙŠØ­", show_2fa=True)

        user_id = user['_id']
        session['user_id'] = user_id
        session['username'] = user['username']
        session['display_name'] = user.get('display_name', username)
        session['avatar'] = user.get('avatar', 'ðŸ˜Š')
        session['photo_url'] = user.get('photo_url', '')
        session['theme'] = user.get('theme', 'dark')

        sess_id = str(uuid.uuid4())
        session['session_id'] = sess_id
        ua = request.headers.get('User-Agent','')
        device = 'Ù…ÙˆØ¨Ø§ÙŠÙ„' if 'Mobile' in ua else 'ÙƒÙ…Ø¨ÙŠÙˆØªØ±'
        fb_set(f'sessions/{user_id}/{sess_id}', {
            'device_name': device,
            'location': '',
            'created_at': now()
        })
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'user_id' in session and 'session_id' in session:
        fb_delete(f'sessions/{session["user_id"]}/{session["session_id"]}')
    session.clear()
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET','POST'])
def forgot_password():
    msg = None
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        users = fb_query('users')
        user = next((u for u in users if u.get('email') == email), None)
        if user:
            parts = email.split('@')
            masked = parts[0][:2] + '***@' + parts[1]
            msg = f"ØªÙ… Ø¥Ø±Ø³Ø§Ù„ ÙƒÙ„Ù…Ø© Ø§Ù„Ù…Ø±ÙˆØ± Ø¥Ù„Ù‰ {masked}"
        else:
            msg = "Ø§Ù„Ø¨Ø±ÙŠØ¯ ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯"
    return render_template('forgot_password.html', msg=msg)

# â”€â”€â”€ Home â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/')
@login_required
def home():
    posts_data = fb_query('posts')
    posts_data.sort(key=lambda x: x.get('created_at',''), reverse=True)
    posts_data = [p for p in posts_data if not p.get('channel_id')][:50]

    # Add user info and like info to each post
    posts = []
    for p in posts_data:
        u = get_user_by_id(p.get('user_id',''))
        if u:
            p['username'] = u.get('username','')
            p['display_name'] = u.get('display_name', u.get('username',''))
            p['avatar'] = u.get('avatar','ðŸ˜Š')
            p['photo_url'] = u.get('photo_url','')
            p['is_verified'] = u.get('is_verified', False)
            p['is_restricted'] = u.get('is_restricted', False)
            p['restrict_label'] = u.get('restrict_label','')
        likes = fb_get(f'likes/{p["_id"]}') or {}
        p['like_count'] = len(likes)
        p['user_liked'] = session['user_id'] in likes
        comments = fb_get(f'comments/{p["_id"]}') or {}
        p['comment_count'] = len(comments) if isinstance(comments, dict) else 0
        p['id'] = p['_id']
        # Track view
        fb_update(f'posts/{p["_id"]}', {'views': (p.get('views') or 0) + 1})
        posts.append(p)

    stories_data = fb_query('stories')
    stories_data.sort(key=lambda x: x.get('created_at',''), reverse=True)
    stories = []
    for s in stories_data[:20]:
        u = get_user_by_id(s.get('user_id',''))
        if u:
            s['username'] = u.get('username','')
            s['avatar'] = u.get('avatar','ðŸ˜Š')
            s['photo_url'] = u.get('photo_url','')
        stories.append(s)

    ctx = get_user_context()
    return render_template('home.html', posts=posts, stories=stories, **ctx)

# â”€â”€â”€ Posts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/post', methods=['POST'])
@login_required
def create_post():
    content = request.form.get('content','').strip()
    image_url = ''
    try:
        if 'image' in request.files:
            saved = save_photo(request.files['image'])
            if saved: image_url = saved
    except: pass
    if content or image_url:
        import re
        tags = ' '.join(re.findall(r'#\w+', content)) if content else ''
        fb_push('posts', {
            'user_id': session['user_id'],
            'content': content,
            'hashtags': tags,
            'image_url': image_url,
            'created_at': now()
        })
    return redirect(url_for('home'))

@app.route('/like/<post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    likes = fb_get(f'likes/{post_id}') or {}
    uid = session['user_id']
    if uid in likes:
        fb_delete(f'likes/{post_id}/{uid}')
        liked = False
    else:
        fb_set(f'likes/{post_id}/{uid}', True)
        liked = True
        post = fb_get(f'posts/{post_id}')
        if post and post.get('user_id') != uid:
            add_notif(post['user_id'], f"â¤ï¸ {session['display_name']} Ø£Ø¹Ø¬Ø¨ Ø¨Ù…Ù†Ø´ÙˆØ±Ùƒ", 'notif_likes')
    likes = fb_get(f'likes/{post_id}') or {}
    return jsonify({"liked": liked, "count": len(likes)})

@app.route('/comment/<post_id>', methods=['POST'])
@login_required
def comment(post_id):
    content = request.form['content'].strip()
    if content:
        fb_push(f'comments/{post_id}', {
            'user_id': session['user_id'],
            'content': content,
            'created_at': now()
        })
        post = fb_get(f'posts/{post_id}')
        if post and post.get('user_id') != session['user_id']:
            add_notif(post['user_id'], f"ðŸ’¬ {session['display_name']} Ø¹Ù„Ù‘Ù‚ Ø¹Ù„Ù‰ Ù…Ù†Ø´ÙˆØ±Ùƒ", 'notif_likes')
    return redirect(url_for('home'))

@app.route('/delete_post/<post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = fb_get(f'posts/{post_id}')
    if post and post.get('user_id') == session['user_id']:
        fb_delete(f'posts/{post_id}')
    return redirect(url_for('home'))

@app.route('/story', methods=['POST'])
@login_required
def create_story():
    content = request.form['content'].strip()
    emoji = request.form.get('emoji','âœ¨')
    if content:
        fb_push('stories', {
            'user_id': session['user_id'],
            'content': content,
            'emoji': emoji,
            'created_at': now()
        })
    return redirect(url_for('home'))

# â”€â”€â”€ Profile â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/profile/<username>')
@login_required
def profile(username):
    user = get_user_by_username(username)
    if not user: return "Ù…Ø³ØªØ®Ø¯Ù… ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯", 404
    uid = user['_id']

    posts_data = fb_query('posts')
    posts = []
    for p in posts_data:
        if p.get('user_id') == uid and not p.get('channel_id'):
            likes = fb_get(f'likes/{p["_id"]}') or {}
            p['like_count'] = len(likes)
            p['user_liked'] = session['user_id'] in likes
            p['id'] = p['_id']
            p['username'] = user.get('username','')
            p['display_name'] = user.get('display_name','')
            p['avatar'] = user.get('avatar','ðŸ˜Š')
            p['photo_url'] = user.get('photo_url','')
            p['is_verified'] = user.get('is_verified', False)
            p['is_restricted'] = user.get('is_restricted', False)
            posts.append(p)
    posts.sort(key=lambda x: x.get('created_at',''), reverse=True)

    follows_data = fb_get('follows') or {}
    followers = sum(1 for v in follows_data.values() if isinstance(v,dict) and v.get('following_id') == uid)
    following_count = sum(1 for v in follows_data.values() if isinstance(v,dict) and v.get('follower_id') == uid)
    is_following = any(v.get('follower_id') == session['user_id'] and v.get('following_id') == uid
                      for v in follows_data.values() if isinstance(v,dict))

    channels_data = fb_query('channels')
    channels = [ch for ch in channels_data if ch.get('owner_id') == uid]

    ctx = get_user_context()
    return render_template('profile.html', user=user, posts=posts, followers=followers,
                          following=following_count, is_following=is_following, channels=channels, **ctx)

@app.route('/follow/<user_id>', methods=['POST'])
@login_required
def follow(user_id):
    if user_id == session['user_id']:
        return jsonify({"error": "Ù„Ø§ ÙŠÙ…ÙƒÙ†Ùƒ Ù…ØªØ§Ø¨Ø¹Ø© Ù†ÙØ³Ùƒ"})
    follows = fb_get('follows') or {}
    existing = None
    for k, v in follows.items():
        if isinstance(v,dict) and v.get('follower_id') == session['user_id'] and v.get('following_id') == user_id:
            existing = k
            break
    if existing:
        fb_delete(f'follows/{existing}')
        following = False
    else:
        fb_push('follows', {'follower_id': session['user_id'], 'following_id': user_id, 'created_at': now()})
        following = True
        add_notif(user_id, f"ðŸ‘¤ {session['display_name']} Ø¨Ø¯Ø£ Ù…ØªØ§Ø¨Ø¹ØªÙƒ", 'notif_follows')
    return jsonify({"following": following})

# â”€â”€â”€ Search â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/search')
@login_required
def search():
    q = request.args.get('q','').strip().lower()
    users, posts, channels = [], [], []
    if q:
        all_users = fb_query('users')
        users = [u for u in all_users if q in u.get('username','').lower() or q in u.get('display_name','').lower()]
        all_posts = fb_query('posts')
        for p in all_posts:
            if q in p.get('content','').lower() and not p.get('channel_id'):
                u = get_user_by_id(p.get('user_id',''))
                if u:
                    p['username'] = u.get('username','')
                    p['display_name'] = u.get('display_name','')
                    p['avatar'] = u.get('avatar','ðŸ˜Š')
                    p['photo_url'] = u.get('photo_url','')
                posts.append(p)
        all_channels = fb_query('channels')
        channels = [ch for ch in all_channels if q in ch.get('name','').lower() or q in ch.get('username','').lower()]
    ctx = get_user_context()
    return render_template('search.html', users=users, posts=posts, channels=channels, q=q, **ctx)

# â”€â”€â”€ Notifications â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/notifications')
@login_required
def notifications():
    notifs_data = fb_get(f'notifications/{session["user_id"]}') or {}
    notifs = []
    for k, v in notifs_data.items():
        if isinstance(v, dict):
            v['_id'] = k
            notifs.append(v)
    notifs.sort(key=lambda x: x.get('created_at',''), reverse=True)
    # Mark all as read
    for n in notifs:
        if not n.get('is_read'):
            fb_update(f'notifications/{session["user_id"]}/{n["_id"]}', {'is_read': True})
    ctx = get_user_context()
    return render_template('notifications.html', notifs=notifs, **ctx)

# â”€â”€â”€ Messages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/messages')
@login_required
def messages():
    all_users = fb_query('users')
    convos = []
    for u in all_users:
        if u['_id'] == session['user_id']: continue
        conv_id = '_'.join(sorted([session['user_id'], u['_id']]))
        msgs = fb_get(f'messages/{conv_id}') or {}
        if msgs:
            msg_list = [v for v in msgs.values() if isinstance(v,dict)]
            msg_list.sort(key=lambda x: x.get('created_at',''))
            last = msg_list[-1] if msg_list else None
            unread = sum(1 for m in msg_list if m.get('receiver_id') == session['user_id'] and not m.get('is_read'))
            convos.append({
                'id': u['_id'],
                'username': u.get('username',''),
                'display_name': u.get('display_name', u.get('username','')),
                'avatar': u.get('avatar','ðŸ˜Š'),
                'photo_url': u.get('photo_url',''),
                'last_msg': last.get('content','') if last else '',
                'unread': unread
            })
    convos.sort(key=lambda x: x.get('last_msg',''), reverse=True)
    ctx = get_user_context()
    return render_template('messages.html', convos=convos, **ctx)

@app.route('/messages/<other_id>')
@login_required
def chat(other_id):
    other = get_user_by_id(other_id)
    if not other: return "Ù…Ø³ØªØ®Ø¯Ù… ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯", 404
    conv_id = '_'.join(sorted([session['user_id'], other_id]))
    msgs_data = fb_get(f'messages/{conv_id}') or {}
    msgs = []
    for k, v in msgs_data.items():
        if isinstance(v, dict):
            v['_id'] = k
            v['sender_id_val'] = v.get('sender_id','')
            msgs.append(v)
    msgs.sort(key=lambda x: x.get('created_at',''))
    # Mark as read
    for m in msgs:
        if m.get('receiver_id') == session['user_id'] and not m.get('is_read'):
            fb_update(f'messages/{conv_id}/{m["_id"]}', {'is_read': True})
    ctx = get_user_context()
    return render_template('chat.html', other=other, msgs=msgs, conv_id=conv_id, **ctx)

@app.route('/send_message/<other_id>', methods=['POST'])
@login_required
def send_message(other_id):
    content = request.form.get('content','').strip()
    image_url = ''
    try:
        if 'image' in request.files:
            saved = save_photo(request.files['image'])
            if saved: image_url = saved
    except: pass
    if content or image_url:
        conv_id = '_'.join(sorted([session['user_id'], other_id]))
        fb_push(f'messages/{conv_id}', {
            'sender_id': session['user_id'],
            'receiver_id': other_id,
            'content': content,
            'image_url': image_url,
            'is_read': False,
            'created_at': now()
        })
        add_notif(other_id, f"ðŸ’¬ Ø±Ø³Ø§Ù„Ø© Ø¬Ø¯ÙŠØ¯Ø© Ù…Ù† {session['display_name']}", 'notif_messages')
    return redirect(url_for('chat', other_id=other_id))

# â”€â”€â”€ Settings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html', **get_user_context())

@app.route('/settings/profile', methods=['GET','POST'])
@login_required
def settings_profile():
    user = get_user_by_id(session['user_id'])
    success = error = None
    if request.method == 'POST':
        display_name = request.form.get('display_name','').strip()
        bio = request.form.get('bio','').strip()
        avatar = request.form.get('avatar','ðŸ˜Š').strip()
        new_username = request.form.get('username_edit','').strip().lstrip('@')
        photo_url = user.get('photo_url','')
        try:
            if 'photo' in request.files:
                saved = save_photo(request.files['photo'])
                if saved: photo_url = saved
        except: pass

        update_data = {
            'display_name': display_name or user.get('display_name',''),
            'bio': bio,
            'avatar': avatar or 'ðŸ˜Š',
            'photo_url': photo_url
        }
        if new_username and new_username != user.get('username'):
            existing = get_user_by_username(new_username)
            if existing:
                error = "Ø§Ø³Ù… Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ù…Ø³ØªØ®Ø¯Ù… Ù…Ø³Ø¨Ù‚Ø§Ù‹"
            else:
                update_data['username'] = new_username
                session['username'] = new_username

        if not error:
            fb_update(f'users/{session["user_id"]}', update_data)
            session['display_name'] = update_data['display_name']
            session['avatar'] = update_data['avatar']
            session['photo_url'] = photo_url
            success = "ØªÙ… Ø­ÙØ¸ Ø§Ù„ØªØºÙŠÙŠØ±Ø§Øª âœ…"
            user = get_user_by_id(session['user_id'])

    return render_template('settings_profile.html', user=user, success=success, error=error, **get_user_context())

@app.route('/settings/privacy', methods=['GET'])
@login_required
def settings_privacy():
    user = get_user_by_id(session['user_id'])
    return render_template('settings_privacy.html', user=user, **get_user_context())

@app.route('/settings/privacy/toggle', methods=['POST'])
@login_required
def toggle_private():
    user = get_user_by_id(session['user_id'])
    fb_update(f'users/{session["user_id"]}', {'is_private': not user.get('is_private', False)})
    return redirect(url_for('settings_privacy'))

@app.route('/settings/privacy/activity', methods=['POST'])
@login_required
def toggle_activity():
    user = get_user_by_id(session['user_id'])
    fb_update(f'users/{session["user_id"]}', {'show_activity': not user.get('show_activity', True)})
    return redirect(url_for('settings_privacy'))

@app.route('/settings/security')
@login_required
def settings_security():
    user = get_user_by_id(session['user_id'])
    sessions_data = fb_get(f'sessions/{session["user_id"]}') or {}
    sessions_list = []
    for k, v in sessions_data.items():
        if isinstance(v, dict):
            v['id'] = k
            sessions_list.append(v)
    return render_template('settings_security.html', user=user, sessions=sessions_list,
                          current_session_id=session.get('session_id'), **get_user_context())

@app.route('/settings/security/logout-session/<sess_id>', methods=['POST'])
@login_required
def logout_session(sess_id):
    fb_delete(f'sessions/{session["user_id"]}/{sess_id}')
    return redirect(url_for('settings_security'))

@app.route('/settings/security/2fa', methods=['GET'])
@login_required
def settings_2fa():
    user = get_user_by_id(session['user_id'])
    return render_template('settings_2fa.html', user=user, **get_user_context())

@app.route('/settings/security/2fa/enable', methods=['POST'])
@login_required
def enable_2fa():
    code = request.form['two_fa_code'].strip()
    confirm = request.form['two_fa_confirm'].strip()
    if code != confirm:
        user = get_user_by_id(session['user_id'])
        return render_template('settings_2fa.html', user=user, error="Ø§Ù„Ø±Ù…Ø²Ø§Ù† ØºÙŠØ± Ù…ØªØ·Ø§Ø¨Ù‚Ø§Ù†", **get_user_context())
    fb_update(f'users/{session["user_id"]}', {'two_fa_enabled': True, 'two_fa_code': code})
    return redirect(url_for('settings_2fa'))

@app.route('/settings/security/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    password = request.form['password']
    user = get_user_by_id(session['user_id'])
    if user and bcrypt.checkpw(password.encode(), user['password'].encode()):
        fb_update(f'users/{session["user_id"]}', {'two_fa_enabled': False, 'two_fa_code': ''})
    return redirect(url_for('settings_2fa'))

@app.route('/settings/appearance', methods=['GET','POST'])
@login_required
def settings_appearance():
    if request.method == 'POST':
        theme = request.form.get('theme','dark')
        fb_update(f'users/{session["user_id"]}', {'theme': theme})
        session['theme'] = theme
        return redirect(url_for('settings_appearance'))
    return render_template('settings_appearance.html', **get_user_context())

@app.route('/settings/notifications', methods=['GET','POST'])
@login_required
def settings_notifications():
    user = get_user_by_id(session['user_id'])
    if request.method == 'POST':
        fields = ['notif_likes','notif_follows','notif_visits','notif_reposts','notif_messages','notif_channels']
        update = {f: (f in request.form) for f in fields}
        fb_update(f'users/{session["user_id"]}', update)
        return redirect(url_for('settings_notifications'))
    return render_template('settings_notifications.html', user=user, **get_user_context())

@app.route('/settings/audience', methods=['GET','POST'])
@login_required
def settings_audience():
    user = get_user_by_id(session['user_id'])
    if request.method == 'POST':
        fb_update(f'users/{session["user_id"]}', {'age_restriction': request.form.get('age_restriction','all')})
        return redirect(url_for('settings_audience'))
    return render_template('settings_audience.html', user=user, **get_user_context())

@app.route('/settings/share-profile')
@login_required
def share_profile():
    link = f"https://n-py.onrender.com/profile/{session['username']}"
    return render_template('share_profile.html', link=link, **get_user_context())

# â”€â”€â”€ Help & Support â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/help')
@login_required
def help_center():
    return render_template('help.html', **get_user_context())

@app.route('/help/account-info')
@login_required
def help_account_info():
    user = get_user_by_id(session['user_id'])
    return render_template('help_account_info.html', user=user, **get_user_context())

@app.route('/help/hacked', methods=['GET','POST'])
@login_required
def help_hacked():
    success = None
    if request.method == 'POST':
        msg = request.form.get('message','').strip()
        if msg:
            fb_push('support_messages', {'user_id': session['user_id'], 'username': session['username'], 'content': msg, 'created_at': now()})
            success = "ØªÙ… Ø¥Ø±Ø³Ø§Ù„ Ø±Ø³Ø§Ù„ØªÙƒ Ù„Ù„Ø¯Ø¹Ù… Ø§Ù„ÙÙ†ÙŠ âœ…"
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

# â”€â”€â”€ Channels â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/channels')
@login_required
def channels():
    chans = fb_query('channels')
    for ch in chans:
        subs = fb_get(f'channel_subs/{ch["_id"]}') or {}
        ch['subscribers'] = ch.get('base_subscribers', 1) + len(subs)
        ch['id'] = ch['_id']
    chans.sort(key=lambda x: x.get('subscribers',0), reverse=True)
    return render_template('channels.html', channels=chans, **get_user_context())

@app.route('/channel/<channel_id>')
@login_required
def view_channel(channel_id):
    channel = fb_get(f'channels/{channel_id}')
    if not channel: return "Ù‚Ù†Ø§Ø© ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø©", 404
    channel['id'] = channel_id
    channel['_id'] = channel_id
    subs = fb_get(f'channel_subs/{channel_id}') or {}
    channel['subscribers'] = channel.get('base_subscribers', 1) + len(subs)
    is_subscribed = session['user_id'] in subs

    posts_data = fb_query('posts')
    posts = []
    for p in posts_data:
        if p.get('channel_id') == channel_id:
            likes = fb_get(f'likes/{p["_id"]}') or {}
            p['like_count'] = len(likes)
            p['user_liked'] = session['user_id'] in likes
            p['id'] = p['_id']
            posts.append(p)
    posts.sort(key=lambda x: x.get('created_at',''), reverse=True)

    return render_template('channel_view.html', channel=channel, posts=posts,
                          is_subscribed=is_subscribed, **get_user_context())

@app.route('/channel/<channel_id>/subscribe', methods=['POST'])
@login_required
def subscribe_channel(channel_id):
    fb_set(f'channel_subs/{channel_id}/{session["user_id"]}', True)
    return redirect(url_for('view_channel', channel_id=channel_id))

@app.route('/channel/<channel_id>/unsubscribe', methods=['POST'])
@login_required
def unsubscribe_channel(channel_id):
    fb_delete(f'channel_subs/{channel_id}/{session["user_id"]}')
    return redirect(url_for('view_channel', channel_id=channel_id))

@app.route('/channel/<channel_id>/post', methods=['POST'])
@login_required
def post_in_channel(channel_id):
    channel = fb_get(f'channels/{channel_id}')
    if not channel or channel.get('owner_id') != session['user_id']:
        return "ØºÙŠØ± Ù…ØµØ±Ø­", 403
    content = request.form['content'].strip()
    if content:
        fb_push('posts', {'user_id': session['user_id'], 'channel_id': channel_id, 'content': content, 'created_at': now()})
    return redirect(url_for('view_channel', channel_id=channel_id))

@app.route('/channel/create', methods=['GET','POST'])
@login_required
def create_channel():
    if request.method == 'POST':
        name = request.form['name'].strip()
        username = request.form['username'].strip().lstrip('@')
        desc = request.form.get('description','').strip()
        avatar = request.form.get('avatar','ðŸ“¡').strip()
        cover_url = ''
        if 'cover' in request.files:
            saved = save_photo(request.files['cover'])
            if saved: cover_url = saved
        # Check username
        chans = fb_query('channels')
        if any(ch.get('username') == username for ch in chans):
            return render_template('create_channel.html', error="Ø§Ø³Ù… Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ù…Ø³ØªØ®Ø¯Ù… Ù…Ø³Ø¨Ù‚Ø§Ù‹", **get_user_context())
        fb_push('channels', {'owner_id': session['user_id'], 'name': name, 'username': username,
                             'description': desc, 'avatar': avatar, 'cover_url': cover_url,
                             'is_verified': False, 'base_subscribers': 1, 'created_at': now()})
        return redirect(url_for('channels'))
    return render_template('create_channel.html', **get_user_context())

# â”€â”€â”€ Admin â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error="ÙƒÙ„Ù…Ø© Ù…Ø±ÙˆØ± Ø®Ø§Ø·Ø¦Ø©")
    return render_template('admin_login.html')

@app.route('/admin')
@admin_required
def admin_dashboard():
    users = fb_query('users')
    posts = fb_query('posts')
    support_msgs = fb_query('support_messages')
    sessions_data = fb_get('sessions') or {}
    active = len(sessions_data)
    stats = {'users': len(users), 'posts': len(posts), 'messages': 0, 'active': active}

    # Get all messages count
    msgs_data = fb_get('messages') or {}
    msg_list = []
    for conv_id, conv in msgs_data.items():
        if isinstance(conv, dict):
            for mid, m in conv.items():
                if isinstance(m, dict):
                    stats['messages'] += 1
                    m['conv_id'] = conv_id
                    msg_list.append(m)

    return render_template('admin.html', users=users, posts=posts, messages=msg_list[:100],
                          support_msgs=support_msgs, stats=stats)

@app.route('/admin/user/<user_id>')
@admin_required
def admin_view_user(user_id):
    user = get_user_by_id(user_id)
    posts = [p for p in fb_query('posts') if p.get('user_id') == user_id]
    return render_template('admin_user.html', user=user, posts=posts, user_msgs=[])

@app.route('/admin/ban/<user_id>', methods=['POST'])
@admin_required
def admin_ban(user_id):
    user = get_user_by_id(user_id)
    ban_until = request.form.get('ban_until','')
    new_status = not user.get('is_banned', False)
    fb_update(f'users/{user_id}', {'is_banned': new_status, 'ban_until': ban_until if new_status else ''})
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    fb_delete(f'users/{user_id}')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_post/<post_id>', methods=['POST'])
@admin_required
def admin_delete_post(post_id):
    fb_delete(f'posts/{post_id}')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/verify/<user_id>', methods=['POST'])
@admin_required
def admin_verify(user_id):
    user = get_user_by_id(user_id)
    fb_update(f'users/{user_id}', {'is_verified': not user.get('is_verified', False)})
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/restrict/<user_id>', methods=['POST'])
@admin_required
def admin_restrict(user_id):
    label = request.form.get('label','Ù…Ù‚ÙŠÙ‘Ø¯')
    user = get_user_by_id(user_id)
    new = not user.get('is_restricted', False)
    fb_update(f'users/{user_id}', {'is_restricted': new, 'restrict_label': label if new else ''})
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/broadcast', methods=['POST'])
@admin_required
def admin_broadcast():
    content = request.form.get('content','').strip()
    if content:
        users = fb_query('users')
        for u in users:
            fb_push(f'notifications/{u["_id"]}', {'content': f"ðŸ“¢ {content}", 'is_read': False, 'created_at': now()})
    return redirect(url_for('admin_dashboard'))


@app.route("/view/<post_id>", methods=["POST"])
@login_required
def track_view(post_id):
    views = fb_get(f"views/{post_id}") or {}
    uid = session["user_id"]
    if uid not in views:
        fb_set(f"views/{post_id}/{uid}", True)
    count = len(fb_get(f"views/{post_id}") or {})
    return jsonify({"count": count})

@app.route("/admin/boost", methods=["POST"])
@admin_required
def admin_boost():
    boost_type = request.form.get("boost_type")
    target = request.form.get("target","").strip().lstrip("@")
    amount = int(request.form.get("amount", 0))
    boost_msg = None

    user = get_user_by_username(target)
    if not user:
        # try by ID
        user = get_user_by_id(target)

    if not user:
        boost_msg = "âŒ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯"
    elif boost_type == "followers":
        current = int(user.get("fake_followers", 0))
        fb_update(f"users/{user['_id']}", {"fake_followers": current + amount})
        boost_msg = f"âœ… ØªÙ… Ø¥Ø¶Ø§ÙØ© {amount} Ù…ØªØ§Ø¨Ø¹ Ù„Ù€ @{user['username']}"
    elif boost_type == "views":
        current = int(user.get("fake_views", 0))
        fb_update(f"users/{user['_id']}", {"fake_views": current + amount})
        boost_msg = f"âœ… ØªÙ… Ø¥Ø¶Ø§ÙØ© {amount} Ù…Ø´Ø§Ù‡Ø¯Ø© Ù„Ù€ @{user['username']}"
    elif boost_type == "likes":
        current = int(user.get("fake_likes", 0))
        fb_update(f"users/{user['_id']}", {"fake_likes": current + amount})
        boost_msg = f"âœ… ØªÙ… Ø¥Ø¶Ø§ÙØ© {amount} Ø¥Ø¹Ø¬Ø§Ø¨ Ù„Ù€ @{user['username']}"

    # Re-render admin page with boost_msg
    users = fb_query("users")
    posts = fb_query("posts")
    support_msgs = fb_query("support_messages")
    stats = {"users": len(users), "posts": len(posts), "messages": 0, "active": 0}
    return render_template("admin.html", users=users, posts=posts, messages=[], support_msgs=support_msgs, stats=stats, boost_msg=boost_msg)

@app.route("/admin/verify-item", methods=["POST"])
@admin_required
def admin_verify_item():
    verify_type = request.form.get("verify_type")
    target = request.form.get("target","").strip().lstrip("@")
    verify_msg = None

    if verify_type == "user":
        user = get_user_by_username(target) or get_user_by_id(target)
        if user:
            fb_update(f"users/{user['_id']}", {"is_verified": True})
            verify_msg = f"âœ… ØªÙ… ØªÙˆØ«ÙŠÙ‚ @{user['username']}"
        else:
            verify_msg = "âŒ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯"
    elif verify_type == "channel":
        channels = fb_query("channels")
        ch = next((c for c in channels if c.get("username") == target or c.get("_id") == target), None)
        if ch:
            fb_update(f"channels/{ch['_id']}", {"is_verified": True})
            verify_msg = f"âœ… ØªÙ… ØªÙˆØ«ÙŠÙ‚ Ù‚Ù†Ø§Ø© {ch['name']}"
        else:
            verify_msg = "âŒ Ø§Ù„Ù‚Ù†Ø§Ø© ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø©"

    users = fb_query("users")
    posts = fb_query("posts")
    support_msgs = fb_query("support_messages")
    stats = {"users": len(users), "posts": len(posts), "messages": 0, "active": 0}
    return render_template("admin.html", users=users, posts=posts, messages=[], support_msgs=support_msgs, stats=stats, verify_msg=verify_msg)

@app.route('/admin/boost', methods=['POST'])
@admin_required
def admin_boost():
    boost_type = request.form.get('boost_type','followers')
    target = request.form.get('target','').strip()
    amount = int(request.form.get('amount', 0))
    boost_msg = None

    if target and amount > 0:
        # Find user
        users = fb_query('users')
        user = next((u for u in users if u.get('username') == target or u.get('_id') == target), None)
        if user:
            uid = user['_id']
            if boost_type == 'followers':
                for i in range(min(amount, 10000)):
                    fake_id = f'fake_{uid}_{i}_{now()[:10]}'
                    fb_set(f'follows/{fake_id}', {'follower_id': fake_id, 'following_id': uid, 'created_at': now()})
                boost_msg = f'ØªÙ… Ø¥Ø¶Ø§ÙØ© {amount} Ù…ØªØ§Ø¨Ø¹ Ù„Ù€ @{user["username"]} âœ…'
            elif boost_type == 'views':
                posts_data = fb_query('posts')
                user_posts = [p for p in posts_data if p.get('user_id') == uid]
                for p in user_posts[:10]:
                    current = p.get('views', 0) or 0
                    fb_update(f'posts/{p["_id"]}', {'views': current + amount})
                boost_msg = f'ØªÙ… Ø¥Ø¶Ø§ÙØ© {amount} Ù…Ø´Ø§Ù‡Ø¯Ø© Ù„Ù…Ù†Ø´ÙˆØ±Ø§Øª @{user["username"]} âœ…'
            elif boost_type == 'likes':
                posts_data = fb_query('posts')
                user_posts = [p for p in posts_data if p.get('user_id') == uid]
                for p in user_posts[:5]:
                    for i in range(min(amount, 1000)):
                        fb_set(f'likes/{p["_id"]}/fake_{i}_{uid}', True)
                boost_msg = f'ØªÙ… Ø¥Ø¶Ø§ÙØ© {amount} Ø¥Ø¹Ø¬Ø§Ø¨ Ù„Ù…Ù†Ø´ÙˆØ±Ø§Øª @{user["username"]} âœ…'
        else:
            boost_msg = 'Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯ âŒ'

    users = fb_query('users')
    posts = fb_query('posts')
    support_msgs = fb_query('support_messages')
    stats = {'users': len(users), 'posts': len(posts), 'messages': 0, 'active': 0}
    return render_template('admin.html', users=users, posts=posts, messages=[], support_msgs=support_msgs, stats=stats, boost_msg=boost_msg)

@app.route('/admin/verify_by_username', methods=['POST'])
@admin_required
def admin_verify_by_username():
    target = request.form.get('target','').strip()
    target_type = request.form.get('target_type','user')
    verify_msg = None

    if target:
        if target_type == 'user':
            users = fb_query('users')
            user = next((u for u in users if u.get('username') == target or u.get('_id') == target), None)
            if user:
                new_status = not user.get('is_verified', False)
                fb_update(f'users/{user["_id"]}', {'is_verified': new_status})
                verify_msg = f'ØªÙ… {"ØªÙˆØ«ÙŠÙ‚" if new_status else "Ø¥Ù„ØºØ§Ø¡ ØªÙˆØ«ÙŠÙ‚"} @{user["username"]} âœ…'
            else:
                verify_msg = 'Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯ âŒ'
        else:
            channels = fb_query('channels')
            channel = next((c for c in channels if c.get('username') == target or c.get('_id') == target), None)
            if channel:
                new_status = not channel.get('is_verified', False)
                fb_update(f'channels/{channel["_id"]}', {'is_verified': new_status})
                verify_msg = f'ØªÙ… {"ØªÙˆØ«ÙŠÙ‚" if new_status else "Ø¥Ù„ØºØ§Ø¡ ØªÙˆØ«ÙŠÙ‚"} Ù‚Ù†Ø§Ø© {channel["name"]} âœ…'
            else:
                verify_msg = 'Ø§Ù„Ù‚Ù†Ø§Ø© ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø© âŒ'

    users = fb_query('users')
    posts = fb_query('posts')
    support_msgs = fb_query('support_messages')
    stats = {'users': len(users), 'posts': len(posts), 'messages': 0, 'active': 0}
    return render_template('admin.html', users=users, posts=posts, messages=[], support_msgs=support_msgs, stats=stats, verify_msg=verify_msg)

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
