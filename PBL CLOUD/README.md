# CloudVote - Simple Backend + Face verification + Chatbot

This repository contains a lightweight Flask backend and static front-end pages for a demo voting app. New features in this branch:

- Face verification (client-side descriptors via face-api.js, server stores descriptors in `data/faces.json`).
- AI chatbot endpoint that proxies to OpenAI (`/api/chat`) and a simple `chat.html` UI.

Files of interest:
- `app.py` - Flask app exposing API endpoints and serving static pages.
- `requirements.txt` - Python dependencies (Flask, flask-cors, openai, gunicorn, pytest).
- `chat.html` - Simple chat UI that posts to `/api/chat`.
- `face.html` - Webcam-based enrol/verify UI using face-api.js (client-side models required).
- `data/*.json` - file-backed storage (users, votes, faces, admin config).

Quick start (Windows PowerShell):

1) Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2) Required environment variables (recommended to set before running):

```powershell
#$env:FLASK_SECRET = 'a-strong-secret'
#$env:ADMIN_PASSWORD = 'vote'      # optional override for admin
#$env:OPENAI_API_KEY = 'sk-...'    # required for /api/chat to work
#$env:FACE_MATCH_THRESHOLD = '0.6' # optional, default 0.6
```

3) Run the server (development only):

```powershell
.\.venv\Scripts\python.exe app.py
```

4) Open the UI in your browser:
- Home: `/` (index.html)
- Voter Login: `/login.html`
- Voting: `/vote.html`
- Admin Dashboard: `/admin.html` (manage voters, view results, run tests)
- Chat UI: `/chat.html` (AI chatbot — requires `OPENAI_API_KEY` to work)
- Face enroll/verify: `/face.html` (requires face-api.js models; see below)
- Candidates: `/candidates.html` (view registered candidates with face thumbnails)

Chatbot integration (chat.html + /api/chat):
- Frontend (`chat.html`) sends user messages to backend `/api/chat` endpoint via fetch.
- Backend proxies the message to OpenAI's GPT API (requires `OPENAI_API_KEY` env var).
- Responses are displayed in the chat UI with error handling for API failures.
- To enable: set `$env:OPENAI_API_KEY = 'sk-...'` before running the server.
- Example (PowerShell):
  ```powershell
  $env:OPENAI_API_KEY = 'sk-your-openai-key-here'
  .\.venv\Scripts\python.exe app.py
  ```
- Then navigate to http://127.0.0.1:5000/chat.html and start chatting.
- If OPENAI_API_KEY is not set, the chatbot returns "OPENAI_API_KEY not configured on server".

API endpoints (summary):
- `POST /api/login` { id, password }
- `POST /api/vote` { id, option }
- `GET /api/results`
- `POST /api/chat` { message } — **AI chatbot integration**
- `GET /api/users` (list voters)
- `POST /api/users` (create voter) — admin required
- `PUT /api/users/<id>` (update voter) — admin required
- `DELETE /api/users/<id>` — admin required
- `POST /api/face/register` { id, descriptor } — admin required
- `POST /api/face/verify` { descriptor [, id] } — verify by descriptor
- `POST /api/chat` { message }

Face-api.js model files (required for `face.html`)
- `face.html` relies on face-api.js running in the browser. You must download the model files and place them in a `models/` folder at the project root.
- Example model files to download: `tiny_face_detector_model-weights_manifest.json`, `face_landmark_68_model-weights_manifest.json`, `face_recognition_model-weights_manifest.json` and their binary files. You can obtain the models from the face-api.js repo or CDN.

Quick model download (example using PowerShell):

```powershell
mkdir models
# download a few required files (example URLs — check the face-api.js releases for exact paths)
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/justadudewhohacks/face-api.js/master/weights/tiny_face_detector_model-weights_manifest.json" -OutFile models\tiny_face_detector_model-weights_manifest.json
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/justadudewhohacks/face-api.js/master/weights/face_landmark_68_model-weights_manifest.json" -OutFile models\face_landmark_68_model-weights_manifest.json
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/justadudewhohacks/face-api.js/master/weights/face_recognition_model-weights_manifest.json" -OutFile models\face_recognition_model-weights_manifest.json
```

Note: the manifest files reference binary weight files which must also be available at the same path — using the project's release or CDN is simplest.

Security & privacy notes
- Face descriptors are biometric-like data. Treat them as sensitive: ask for explicit consent, encrypt them at rest for production, and comply with applicable regulations.
- The project stores descriptors and votes in JSON files under `data/`. For production use migrate to a secure database.
- Keep `OPENAI_API_KEY` and other secrets out of source control. Use host environment variables.

Deployment notes
- Recommended pattern: host the static frontend on Vercel and the Flask backend on a Python-friendly host (Render, Railway, Fly). Use Vercel rewrites to proxy `/api/*` to the backend to keep same-origin sessions working.
- Alternatively host everything on the same Python host (simpler but you lose Vercel's CDN benefits).

If you'd like I can:
- Add a `vercel.json` with a rewrite that proxies `/api/*` to a backend URL.
- Add a small script to download face-api models into `models/` automatically.
- Add tests for `/api/chat` (mocking OpenAI) and `/api/face/verify` with synthetic descriptors.

If you want me to make any of those changes now, tell me which one and I'll implement it.

---

**Deployment (Vercel / Container) — Quick guide**

This project can be deployed to Vercel using a container (Docker) or hosted on a persistent Python host.

1) Add required environment variables in Vercel (Project → Settings → Environment Variables):

  - `FLASK_SECRET`: strong random secret for Flask sessions
  - `ADMIN_PASSWORD`: admin UI password (override)
  - `OPENAI_API_KEY` (optional): for /api/chat
  - `MONGODB_URI` (recommended for persistence): use a MongoDB Atlas connection string (e.g. `mongodb+srv://user:pass@cluster.mongodb.net/dbname`)
  - `FACE_MATCH_THRESHOLD` (optional): e.g. `0.6`

2) Deploying with Docker on Vercel (container build)

  - I included a `Dockerfile` and `vercel.json` that builds the container via Vercel's Docker builder.
  - Ensure `MONGODB_URI` is set in Vercel; otherwise the app will use file-based storage (ephemeral on Vercel — not suitable for production).

3) Alternative (recommended for production):

  - Use Render, Fly, Railway, or a VM where the filesystem persists, or
  - Use Vercel for static frontend and point `/api/*` to a backend hosted elsewhere (set as external URL in Vercel rewrites).

4) Local test before deploy (PowerShell):

```powershell
$env:FLASK_SECRET = 'change-this-secret'
$env:ADMIN_PASSWORD = 'vote'
$env:MONGODB_URI = 'mongodb://localhost:27017/cloudvote'  # if available
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

5) Notes

- The app now supports MongoDB persistence when `MONGODB_URI` is provided. If not present, it falls back to the existing JSON file storage in `data/`.
- On Vercel the filesystem is ephemeral: changes saved to `data/` will be lost between function invocations or deploys. Use `MONGODB_URI` for durable storage.

If you want, I can:
- Wire the app to S3 for storing images and use MongoDB only for metadata.
- Add a `docker-compose.yml` for local testing with MongoDB.
- Add automated model download for face-api.js models (if you prefer local models rather than CDN).

