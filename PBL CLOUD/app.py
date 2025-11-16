from flask import Flask, request, jsonify, send_from_directory, abort, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from openai import OpenAI, APIError
import json
import base64
import os
from datetime import datetime
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Allow overriding the data directory for tests or deployments via env var
DATA_DIR = os.environ.get('APP_DATA_DIR', os.path.join(BASE_DIR, 'data'))
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
VOTES_FILE = os.path.join(DATA_DIR, 'votes.json')
ADMIN_FILE = os.path.join(DATA_DIR, 'admin.json')
FACES_FILE = os.path.join(DATA_DIR, 'faces.json')
EVENTS_FILE = os.path.join(DATA_DIR, 'events.json')
BIOMETRICS_FILE = os.path.join(DATA_DIR, 'biometrics.json')
VOTE_FACES_FILE = os.path.join(DATA_DIR, 'vote_faces.json')
        
os.makedirs(DATA_DIR, exist_ok=True)

# Optional MongoDB persistence: if MONGODB_URI is provided, use MongoDB instead of file JSON.
MONGODB_URI = os.environ.get('MONGODB_URI')
USE_MONGO = False
mongo_client = None
mongo_db = None
if MONGODB_URI:
    try:
        from pymongo import MongoClient
        mongo_client = MongoClient(MONGODB_URI)
        # Try to infer database from URI, fallback to 'cloudvote'
        try:
            mongo_db = mongo_client.get_default_database()
        except Exception:
            mongo_db = mongo_client['cloudvote']
        USE_MONGO = True
        print('Using MongoDB for persistence')
    except Exception as e:
        print('Failed to initialize MongoDB client, falling back to file storage:', str(e))

# Ensure a place to store candidate thumbnails
STATIC_CANDIDATES = os.path.join(BASE_DIR, 'static', 'candidates')
os.makedirs(STATIC_CANDIDATES, exist_ok=True)

# Simple in-process lock to avoid race conditions when updating votes.json
VOTES_LOCK = threading.Lock()

# Create sample data files if they don't exist
if not os.path.exists(USERS_FILE):
    sample_users = {
        "voters": [
            {"id": "voter1", "name": "Alice", "password_hash": generate_password_hash("password1")},
            {"id": "voter2", "name": "Bob", "password_hash": generate_password_hash("password2")}
        ]
    }
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sample_users, f, indent=2)

if not os.path.exists(VOTES_FILE):
    sample_votes = {
        "options": {
            "optionA": 0,
            "optionB": 0,
            "optionC": 0
        },
        "records": []
    }
    with open(VOTES_FILE, 'w', encoding='utf-8') as f:
        json.dump(sample_votes, f, indent=2)

# Create admin configuration file with a hashed password if it's missing
if not os.path.exists(ADMIN_FILE):
    default_admin_pw = os.environ.get('ADMIN_PASSWORD', 'vote')
    admin_data = {'password_hash': generate_password_hash(default_admin_pw)}
    with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
        json.dump(admin_data, f, indent=2)

# Faces embeddings storage (id -> descriptor list)
if not os.path.exists(FACES_FILE):
    with open(FACES_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f, indent=2)

# Events storage (voting events with dates, titles, descriptions)
if not os.path.exists(EVENTS_FILE):
    sample_events = {
        "events": [
            {
                "id": "event1",
                "title": "2025 General Elections",
                "description": "Presidential and parliamentary elections",
                "start_date": "2025-01-15",
                "end_date": "2025-01-15",
                "status": "active",
                "candidates": ["optionA", "optionB", "optionC"]
            }
        ]
    }
    with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sample_events, f, indent=2)

# Biometric fingerprints storage (fingerprint -> voter_id + event_id)
if not os.path.exists(BIOMETRICS_FILE):
    with open(BIOMETRICS_FILE, 'w', encoding='utf-8') as f:
        json.dump({"fingerprints": []}, f, indent=2)

# Store face data for each vote (vote_id -> face descriptor, image, etc)
if not os.path.exists(VOTE_FACES_FILE):
    with open(VOTE_FACES_FILE, 'w', encoding='utf-8') as f:
        json.dump({"vote_faces": []}, f, indent=2)

app = Flask(__name__, static_folder='.', static_url_path='')

# Flask session secret (use an environment variable in production)
app.secret_key = os.environ.get('FLASK_SECRET', 'devsecret')

# Development fallback admin password
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'vote')

def _is_admin_request():
    # Allow admin via X-Admin-Password header or via session
    admin_pw = request.headers.get('X-Admin-Password')
    if admin_pw and admin_pw == ADMIN_PASSWORD:
        return True
    return bool(session.get('is_admin'))


@app.route('/api/admin/login', methods=['POST'])
def api_admin_login():
    data = request.get_json() or {}
    pw = data.get('password')
    if not pw:
        return jsonify({'error': 'Missing admin password'}), 400
    try:
        with open(ADMIN_FILE, 'r', encoding='utf-8') as f:
            adm = json.load(f)
            stored = adm.get('password_hash', '')
    except Exception:
        stored = os.environ.get('ADMIN_PASSWORD', 'adminpass')

    ok = False
    try:
        ok = check_password_hash(stored, pw)
    except Exception:
        ok = (stored == pw)

    if ok:
        session['is_admin'] = True
        return jsonify({'ok': True})
    return jsonify({'error': 'Invalid admin password'}), 401


@app.route('/api/admin/logout', methods=['POST'])
def api_admin_logout():
    session.pop('is_admin', None)
    return jsonify({'ok': True})


@app.route('/api/admin/status', methods=['GET'])
def api_admin_status():
    return jsonify({'is_admin': bool(session.get('is_admin', False))})


@app.route('/api/admin/change-password', methods=['POST'])
def api_admin_change_password():
    # Require an admin session
    if not session.get('is_admin'):
        return jsonify({'error': 'Admin login required'}), 403
    data = request.get_json() or {}
    old = data.get('old_password')
    new = data.get('new_password')
    if not old or not new:
        return jsonify({'error': 'Missing old or new password'}), 400

    try:
        with open(ADMIN_FILE, 'r', encoding='utf-8') as f:
            adm = json.load(f)
            stored = adm.get('password_hash', '')
    except Exception:
        return jsonify({'error': 'Admin configuration missing'}), 500

    # verifying old password
    ok = False
    try:
        ok = check_password_hash(stored, old)
    except Exception:
        ok = (stored == old)
    if not ok:
        return jsonify({'error': 'Old password is incorrect'}), 401

    # store new hashed password
    new_hash = generate_password_hash(new)
    with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
        json.dump({'password_hash': new_hash}, f, indent=2)
    return jsonify({'ok': True})


@app.route('/api/admin/all-data', methods=['GET'])
def api_admin_all_data():
    # Admin-only: return full datasets (users without raw passwords)
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    users = load_json(USERS_FILE)
    votes = load_json(VOTES_FILE)
    faces = load_json(FACES_FILE)
    # scrub any password fields before returning
    for u in users.get('voters', []):
        if 'password_hash' in u:
            u['password_hash'] = '<hidden>'
        if 'password' in u:
            u.pop('password', None)
    return jsonify({'users': users, 'votes': votes, 'faces': faces})


@app.route('/api/admin/run-tests', methods=['POST'])
def api_admin_run_tests():
    # Admin-only: run pytest and return output. Useful for quick diagnostics.
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    import subprocess, sys
    # build the command to run pytest using the current Python executable
    cmd = [sys.executable, '-m', 'pytest', '-q']
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR, timeout=120)
        out = proc.stdout + '\n' + proc.stderr
        return jsonify({'returncode': proc.returncode, 'output': out})
    except Exception as e:
        return jsonify({'error': 'Failed to run tests', 'details': str(e)}), 500

# Small JSON load/save helpers
def load_json(path):
    """Load JSON data from disk or MongoDB depending on configuration."""
    if USE_MONGO and mongo_db is not None:
        key = os.path.splitext(os.path.basename(path))[0]
        doc = mongo_db['files'].find_one({'_id': key})
        return doc['data'] if doc else {}
    # fallback to file
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    """Save JSON data to disk or MongoDB depending on configuration."""
    if USE_MONGO and mongo_db is not None:
        key = os.path.splitext(os.path.basename(path))[0]
        mongo_db['files'].replace_one({'_id': key}, {'_id': key, 'data': data}, upsert=True)
        return
    # fallback to file
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


# Migration endpoint: copy JSON files into MongoDB when MONGODB_URI is set
@app.route('/admin/migrate_to_mongo', methods=['POST'])
def migrate_to_mongo():
    if not MONGODB_URI:
        return jsonify({'error': 'MONGODB_URI not configured'}), 400
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    try:
        files = [USERS_FILE, VOTES_FILE, FACES_FILE, EVENTS_FILE, BIOMETRICS_FILE, VOTE_FACES_FILE]
        for p in files:
            key = os.path.splitext(os.path.basename(p))[0]
            data = {}
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            mongo_db['files'].replace_one({'_id': key}, {'_id': key, 'data': data}, upsert=True)
        return jsonify({'migrated': True}), 200
    except Exception as e:
        return jsonify({'error': 'Migration failed', 'details': str(e)}), 500

# User helpers
def get_users():
    data = load_json(USERS_FILE)
    return data.get('voters', [])

def save_users(users):
    save_json(USERS_FILE, {'voters': users})

# --- Events API endpoints ---
@app.route('/api/events', methods=['GET'])
def api_events_list():
    """List all voting events"""
    events_data = load_json(EVENTS_FILE)
    return jsonify(events_data.get('events', []))

@app.route('/api/events/<event_id>', methods=['GET'])
def api_events_get(event_id):
    """Get a specific event"""
    events_data = load_json(EVENTS_FILE)
    event = next((e for e in events_data.get('events', []) if e['id'] == event_id), None)
    if not event:
        return jsonify({'error': 'Event not found'}), 404
    return jsonify(event)

@app.route('/api/events', methods=['POST'])
def api_events_create():
    """Create a new voting event (admin only)"""
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    data = request.get_json() or {}
    event_id = data.get('id') or f"event_{int(datetime.utcnow().timestamp())}"
    title = data.get('title')
    description = data.get('description', '')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    candidates = data.get('candidates', ['optionA', 'optionB', 'optionC'])
    
    if not title or not start_date or not end_date:
        return jsonify({'error': 'Missing title, start_date or end_date'}), 400
    
    events_data = load_json(EVENTS_FILE)
    if any(e['id'] == event_id for e in events_data.get('events', [])):
        return jsonify({'error': 'Event id already exists'}), 409
    
    new_event = {
        'id': event_id,
        'title': title,
        'description': description,
        'start_date': start_date,
        'end_date': end_date,
        'status': 'active',
        'candidates': candidates
    }
    events_data['events'].append(new_event)
    save_json(EVENTS_FILE, events_data)
    return jsonify(new_event), 201

@app.route('/api/events/<event_id>', methods=['PUT'])
def api_events_update(event_id):
    """Update an event (admin only)"""
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    data = request.get_json() or {}
    events_data = load_json(EVENTS_FILE)
    event = next((e for e in events_data.get('events', []) if e['id'] == event_id), None)
    if not event:
        return jsonify({'error': 'Event not found'}), 404
    
    # Update allowed fields
    if 'title' in data:
        event['title'] = data['title']
    if 'description' in data:
        event['description'] = data['description']
    if 'status' in data:
        event['status'] = data['status']
    if 'candidates' in data:
        event['candidates'] = data['candidates']
    
    save_json(EVENTS_FILE, events_data)
    return jsonify(event)

@app.route('/api/events/<event_id>/results', methods=['GET'])
def api_events_results(event_id):
    """Get vote results for a specific event"""
    votes_data = load_json(VOTES_FILE)
    # Count votes for this event
    event_votes = [v for v in votes_data.get('records', []) if v.get('event_id') == event_id]
    # Initialize counts for all options
    event = None
    try:
        events_data = load_json(EVENTS_FILE)
        event = next((e for e in events_data.get('events', []) if e['id'] == event_id), None)
    except:
        pass
    
    candidates = event.get('candidates', ['optionA', 'optionB', 'optionC']) if event else ['optionA', 'optionB', 'optionC']
    option_counts = {c: 0 for c in candidates}
    for vote in event_votes:
        option = vote.get('option')
        if option in option_counts:
            option_counts[option] += 1
    
    return jsonify({'event_id': event_id, 'option_counts': option_counts, 'total_votes': len(event_votes)})

# Serve static files from the project root
@app.route('/')
def root():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    # only serve files that exist in the project root for safety
    full = os.path.join(BASE_DIR, filename)
    if os.path.exists(full) and os.path.commonpath([BASE_DIR, full]) == BASE_DIR:
        return send_from_directory(BASE_DIR, filename)
    abort(404)

# API: login (voters)
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    voter_id = data.get('id')
    password = data.get('password')
    if not voter_id or not password:
        return jsonify({'error': 'Missing id or password'}), 400

    users = load_json(USERS_FILE)['voters']
    user = next((u for u in users if u['id'] == voter_id), None)
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401

    # Support password hashes fall back to plaintext for development
    stored = user.get('password_hash') or user.get('password') or ''
    valid = False
    try:
        # try the secure hash check first (handles pbkdf2:, scrypt:, etc. if supported)
        valid = check_password_hash(stored, password)
    except Exception:
        # if check_password_hash cannot parse the stored value, record as False for now
        valid = False

    # If hash check failed (or returned False), also accept plaintext-stored passwords for dev
    if not valid and stored == password:
        valid = True

    if not valid:
        return jsonify({'error': 'Invalid credentials'}), 401

    # In a real app return a signed token. Here return minimal voter info.
    return jsonify({'id': user['id'], 'name': user['name']})


# API: users management
@app.route('/api/users', methods=['GET'])
def api_users_list():
    users = get_users()
    # do not return password hashes
    safe = [{'id': u['id'], 'name': u.get('name'), 'party': u.get('party', '')} for u in users]
    return jsonify({'voters': safe})


@app.route('/api/users', methods=['POST'])
def api_users_create():
    data = request.get_json() or {}
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    voter_id = data.get('id')
    name = data.get('name')
    password = data.get('password')
    party = data.get('party', '')
    if not voter_id or not name or not password:
        return jsonify({'error': 'Missing id, name or password'}), 400

    users = get_users()
    if any(u['id'] == voter_id for u in users):
        return jsonify({'error': 'Voter id already exists'}), 409

    user = {
        'id': voter_id,
        'name': name,
        'party': party,
        'password_hash': generate_password_hash(password)
    }
    users.append(user)
    save_users(users)
    return jsonify({'id': user['id'], 'name': user['name'], 'party': user['party']}), 201


@app.route('/api/users/<voter_id>', methods=['PUT'])
def api_users_update(voter_id):
    data = request.get_json() or {}
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    name = data.get('name')
    party = data.get('party')
    password = data.get('password')

    users = get_users()
    user = next((u for u in users if u['id'] == voter_id), None)
    if not user:
        return jsonify({'error': 'Voter not found'}), 404

    if name is not None:
        user['name'] = name
    if party is not None:
        user['party'] = party
    if password:
        user['password_hash'] = generate_password_hash(password)

    save_users(users)
    return jsonify({'id': user['id'], 'name': user.get('name'), 'party': user.get('party', '')})


@app.route('/api/users/<voter_id>', methods=['DELETE'])
def api_users_delete(voter_id):
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    users = get_users()
    new_users = [u for u in users if u['id'] != voter_id]
    if len(new_users) == len(users):
        return jsonify({'error': 'Voter not found'}), 404
    save_users(new_users)
    return jsonify({'deleted': voter_id})

# API: Biometric verification endpoints
@app.route('/api/biometric/register', methods=['POST'])
def api_biometric_register():
    """Register a biometric fingerprint for a voter"""
    data = request.get_json() or {}
    voter_id = data.get('voter_id')
    biometric_data = data.get('biometric_data')
    biometric_method = data.get('biometric_method', 'fingerprint')
    event_id = data.get('event_id', 'default')
    
    if not voter_id or not biometric_data:
        return jsonify({'error': 'Missing voter_id or biometric_data'}), 400
    
    biometrics = load_json(BIOMETRICS_FILE)
    # Check if this biometric already voted in this event
    for entry in biometrics.get('fingerprints', []):
        if entry['biometric_data'] == biometric_data and entry.get('event_id') == event_id:
            return jsonify({'error': 'This device has already voted in this event', 'biometric_method': entry.get('biometric_method')}), 409
        
        
        
    
    # Register the biometric
    biometrics['fingerprints'].append({
        'voter_id': voter_id,
        'biometric_data': biometric_data,
        'biometric_method': biometric_method,
        'event_id': event_id,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })
    save_json(BIOMETRICS_FILE, biometrics)
    return jsonify({'ok': True, 'message': 'Biometric registered successfully'})

@app.route('/api/biometric/verify', methods=['POST'])
def api_biometric_verify():
    """Verify a biometric fingerprint"""
    data = request.get_json() or {}
    biometric_data = data.get('biometric_data')
    event_id = data.get('event_id', 'default')
    
    if not biometric_data:
        return jsonify({'error': 'Missing biometric_data'}), 400
    
    biometrics = load_json(BIOMETRICS_FILE)
    for entry in biometrics.get('fingerprints', []):
        if entry['biometric_data'] == biometric_data and entry.get('event_id') == event_id:
            return jsonify({'verified': False, 'reason': 'Device has already voted in this event', 'voter_id': entry.get('voter_id')}), 409
    
    return jsonify({'verified': True, 'message': 'Device fingerprint is clear for voting'})

# API: vote
@app.route('/api/vote', methods=['POST'])
def api_vote():
    data = request.get_json() or {}
    voter_id = data.get('id')
    option = data.get('option')
    descriptor = data.get('descriptor')  # Face descriptor (128-dim array)
    image = data.get('image')  # Face image (base64 data URL)
    biometric_data = data.get('biometric_data')
    biometric_method = data.get('biometric_method', 'fingerprint')
    event_id = data.get('event_id', 'default')  # support event_id for multi-event voting
    if not voter_id or not option:
        return jsonify({'error': 'Missing id or option'}), 400
    # Use a lock to avoid race conditions when multiple requests try to write votes
    with VOTES_LOCK:
        votes = load_json(VOTES_FILE)

        # Check biometric fingerprint if provided
        if biometric_data:
            try:
                biometrics = load_json(BIOMETRICS_FILE)
                for entry in biometrics.get('fingerprints', []):
                    if entry['biometric_data'] == biometric_data and entry.get('event_id') == event_id:
                        return jsonify({'error': 'Device has already voted in this event', 'biometric_method': entry.get('biometric_method')}), 409
            except Exception as e:
                app.logger.warning(f'Biometric check error: {e}')

        # If a face descriptor is provided, try to match it against registered faces
        if descriptor:
            try:
                faces = load_faces()
                threshold = float(os.environ.get('FACE_MATCH_THRESHOLD', 0.6))
                best_id = None
                best_dist = float('inf')
                for vid, item in faces.items():
                    try:
                        vec = item.get('descriptor') if isinstance(item, dict) else item
                        d = _euclidean(descriptor, vec)
                        if d < best_dist:
                            best_dist = d
                            best_id = vid
                    except Exception as e:
                        app.logger.warning(f'Face matching error for {vid}: {e}')
                        continue
                # If matched within threshold and that matched voter already voted, block
                if best_id and best_dist <= threshold:
                    if any(r['voter_id'] == best_id and r.get('event_id') == event_id for r in votes['records']):
                        return jsonify({'error': 'Face has already voted', 'matched_id': best_id}), 409
            except Exception as e:
                # If face matching fails for any reason, log and continue with normal checks
                app.logger.warning(f'Face matching exception: {e}')

        # Block double-voting by the same voter id in the same event
        if any(r['voter_id'] == voter_id and r.get('event_id') == event_id for r in votes['records']):
            return jsonify({'error': 'Voter has already voted in this event'}), 409

        if option not in votes['options']:
            return jsonify({'error': 'Invalid option'}), 400

        votes['options'][option] += 1
        vote_record = {
            'voter_id': voter_id,
            'option': option,
            'event_id': event_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        
        # Add biometric data if provided
        if biometric_data:
            vote_record['biometric_method'] = biometric_method
            vote_record['biometric_hash'] = biometric_data[:16]  # store truncated hash for privacy
        
        votes['records'].append(vote_record)
        save_json(VOTES_FILE, votes)
        
        # Register biometric for future duplicate prevention
        if biometric_data:
            try:
                biometrics = load_json(BIOMETRICS_FILE)
                biometrics['fingerprints'].append({
                    'voter_id': voter_id,
                    'biometric_data': biometric_data,
                    'biometric_method': biometric_method,
                    'event_id': event_id,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
                save_json(BIOMETRICS_FILE, biometrics)
            except Exception as e:
                app.logger.warning(f'Failed to register biometric: {e}')

        # Store face data if provided (face descriptor and/or image)
        if descriptor or image:
            try:
                vote_faces = load_json(VOTE_FACES_FILE)
                vote_entry = {
                    'voter_id': voter_id,
                    'event_id': event_id,
                    'option': option,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }
                if descriptor:
                    vote_entry['descriptor'] = descriptor
                if image:
                    # Store image as base64 data URL
                    vote_entry['image'] = image
                vote_faces['vote_faces'].append(vote_entry)
                save_json(VOTE_FACES_FILE, vote_faces)
                app.logger.info(f'Stored face data for vote: {voter_id} in event {event_id}')
            except Exception as e:
                app.logger.warning(f'Failed to store face data: {e}')

    return jsonify({'success': True, 'option_counts': votes['options']})

# API: results
@app.route('/api/results', methods=['GET'])
def api_results():
    votes = load_json(VOTES_FILE)
    return jsonify(votes)


# --- Face verification helpers and endpoints ---------------------------------
def load_faces():
    return load_json(FACES_FILE)

def save_faces(faces):
    save_json(FACES_FILE, faces)

def _euclidean(a, b):
    # simple euclidean distance between two equal-length lists
    try:
        return sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)) ** 0.5
    except Exception:
        return float('inf')


@app.route('/api/face/register', methods=['POST'])
def api_face_register():
    # Admin-only helper to store a face descriptor for a voter id
    if not _is_admin_request():
        return jsonify({'error': 'Admin credentials required'}), 403
    data = request.get_json() or {}
    voter_id = data.get('id')
    descriptor = data.get('descriptor')
    role = data.get('role')  # optional, e.g. 'candidate' or 'voter'
    if not voter_id or not descriptor:
        return jsonify({'error': 'Missing id or descriptor'}), 400
    faces = load_faces()
    # store optional image (base64 data URL or raw base64) as a thumbnail for candidates
    image_url = None
    image_b64 = data.get('image')
    if image_b64:
        # strip possible data: prefix
        if image_b64.startswith('data:'):
            image_b64 = image_b64.split(',', 1)[1]
        try:
            img_bytes = base64.b64decode(image_b64)
            fname = f"{voter_id}.jpg"
            fpath = os.path.join(STATIC_CANDIDATES, fname)
            with open(fpath, 'wb') as imgf:
                imgf.write(img_bytes)
            image_url = f"/static/candidates/{fname}"
        except Exception:
            image_url = None

    entry = {'descriptor': descriptor, 'role': role} if role else descriptor
    if image_url:
        # if legacy format, wrap into dict
        if not isinstance(entry, dict):
            entry = {'descriptor': entry}
        entry['image_url'] = image_url

    faces[voter_id] = entry
    save_faces(faces)
    return jsonify({'ok': True, 'id': voter_id, 'image_url': image_url})


@app.route('/api/face/verify', methods=['POST'])
def api_face_verify():
    # Verify an incoming descriptor against stored descriptors
    data = request.get_json() or {}
    descriptor = data.get('descriptor')
    voter_id = data.get('id')
    if not descriptor:
        return jsonify({'error': 'Missing descriptor'}), 400
    faces = load_faces()
    threshold = float(os.environ.get('FACE_MATCH_THRESHOLD', 0.6))

    # If a voter_id is provided, check only that one
    if voter_id:
        target = faces.get(voter_id)
        if not target:
            return jsonify({'error': 'No face registered for this id'}), 404
        # support older format where target is a list, or new format where it's a dict
        vec = target.get('descriptor') if isinstance(target, dict) else target
        dist = _euclidean(descriptor, vec)
        return jsonify({'match': dist <= threshold, 'distance': dist})

    # Otherwise, find the best match among all registered faces
    best_id = None
    best_dist = float('inf')
    for vid, item in faces.items():
        # item can be a list (legacy) or a dict {'descriptor': [...], 'role': 'candidate'}
        vec = item.get('descriptor') if isinstance(item, dict) else item
        d = _euclidean(descriptor, vec)
        if d < best_dist:
            best_dist = d
            best_id = vid
    if best_id is None:
        return jsonify({'match': False}), 200
    return jsonify({'match': best_dist <= threshold, 'id': best_id, 'distance': best_dist})


# --- Chatbot endpoint (proxy to OpenAI) -------------------------------------
@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json() or {}
    message = data.get('message') or data.get('text')
    if not message:
        return jsonify({'error': 'Missing message'}), 400
    
    api_key = os.environ.get('OPENAI_API_KEY', '')
    
    # If no API key or a demo/test key, run in demo mode
    if not api_key or api_key in ('testkey', 'sk-test', 'demo') or len(api_key) < 20:
        return jsonify({
            'reply': f'[DEMO MODE] Bot received: "{message}". This is demo mode - chatbot responses are simulated. For real AI responses, set a valid OPENAI_API_KEY environment variable before starting the server.'
        }), 200
    
    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.environ.get('OPENAI_MODEL', 'gpt-3.5-turbo'),
            messages=[{'role': 'user', 'content': message}],
            max_tokens=500,
        )
        reply = resp.choices[0].message.content
    except Exception as e:
        error_msg = str(e)
        # Check if it's an API key error
        if 'invalid_api_key' in error_msg or 'Incorrect API key' in error_msg or '401' in error_msg:
            return jsonify({
                'error': 'Invalid API Key',
                'details': 'Your OpenAI API key is invalid or expired. Please check your OPENAI_API_KEY environment variable. Get a valid key from https://platform.openai.com/account/api-keys'
            }), 401

        # Quota / rate limit errors: provide a friendly demo fallback instead of surfacing raw provider error
        if 'insufficient_quota' in error_msg or 'quota' in error_msg or '429' in error_msg or 'rate limit' in error_msg.lower():
            demo_reply = (
                f"[DEMO FALLBACK] The OpenAI account has exceeded its quota or rate limit.\n"
                f"Showing a simulated reply for: \"{message}\".\n"
                "To fix this, check your OpenAI billing and usage at https://platform.openai.com/account/usage or upgrade your plan."
            )
            return jsonify({'reply': demo_reply, 'warning': 'quota_exceeded', 'details': error_msg}), 200

        return jsonify({'error': 'Chat provider error', 'details': error_msg}), 502
    return jsonify({'reply': reply})

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='127.0.0.1', port=5000, debug=debug_mode)
