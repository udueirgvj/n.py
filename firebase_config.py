import firebase_admin
from firebase_admin import credentials, db, storage
import os, json

# Firebase config
FIREBASE_CONFIG = {
    "type": "service_account",
    "project_id": "tttrt-b8c5a",
    "private_key_id": os.environ.get("FIREBASE_KEY_ID", ""),
    "private_key": os.environ.get("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n"),
    "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL", ""),
    "client_id": os.environ.get("FIREBASE_CLIENT_ID", ""),
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": os.environ.get("FIREBASE_CERT_URL", "")
}

DATABASE_URL = "https://tttrt-b8c5a-default-rtdb.asia-southeast1.firebasedatabase.app"
STORAGE_BUCKET = "tttrt-b8c5a.firebasestorage.app"

_initialized = False

def init_firebase():
    global _initialized
    if _initialized:
        return
    try:
        cred = credentials.Certificate(FIREBASE_CONFIG)
        firebase_admin.initialize_app(cred, {
            'databaseURL': DATABASE_URL,
            'storageBucket': STORAGE_BUCKET
        })
        _initialized = True
        print("Firebase initialized successfully")
    except Exception as e:
        print(f"Firebase init error: {e}")

def get_ref(path):
    return db.reference(path)
