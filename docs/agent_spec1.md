# LitFlow — Agent Build Spec

> **Project:** `LitFlow`
> **Goal:** Web portal to upload scanned Islamic book PDFs → OCR → output `.txt` + `.html`
> **Phase:** 1 (PDF → Text/HTML only. EPUB comes later.)
> **Agent instruction:** Build skeleton only. No placeholder logic. Every module must be wired and functional.

---

## 1. Project Structure

Create the following folder structure exactly:

```
./
├── web/
│   ├── app.py                  # Flask app factory
│   ├── auth.py                 # OIDC login/callback/logout, role check
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── dashboard.py        # job list (own + all for admin)
│   │   ├── upload.py           # upload form + enqueue
│   │   ├── jobs.py             # job status + download + preview
│   │   └── admin.py            # admin: all jobs view
│   ├── templates/
│   │   ├── base.html           # Flowbite layout, navbar, auth state
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   ├── upload.html
│   │   ├── job_status.html
│   │   ├── job_preview.html
│   │   └── admin_jobs.html
│   ├── static/
│   │   └── (Flowbite CDN used, no local assets needed)
│   └── db.py                   # SQLite job model via sqlite3 (no ORM)
├── worker/
│   ├── celery_app.py           # Celery init
│   ├── tasks.py                # main pipeline task
│   ├── ocr.py                  # Surya OCR wrapper (CPU mode)
│   └── cleaner.py              # post-OCR text/HTML cleanup
├── jobs/                       # runtime volume (mounted)
├── .env                        # secrets (never commit)
├── .env.example                # committed, all keys present, values empty
├── docker-compose.yml
├── Dockerfile.web
├── Dockerfile.worker
└── pyproject.toml              # uv-compatible
```

---

## 2. Environment Variables

### `.env.example` — commit this:

```env
# Pocket-ID OIDC
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
OIDC_DISCOVERY_URL=
OIDC_REDIRECT_URI=

# JWT Role
OIDC_ADMIN_GROUP=admin

# Flask
SECRET_KEY=
BASE_URL=

# Redis
REDIS_URL=redis://redis:6379/0

# Storage
JOBS_DIR=/jobs
MAX_UPLOAD_MB=500

# Surya
SURYA_CPU_ONLY=true
```

### Loading rules:
- Use `python-dotenv` → `load_dotenv()` in `app.py` and `celery_app.py`
- Never hardcode any value
- `docker-compose.yml` passes `env_file: .env` to `web` and `worker` services

---

## 3. Auth — OIDC via Pocket-ID

**Library:** `Authlib` (Flask integration)

### Flows:
- `GET /login` → redirect to Pocket-ID OIDC authorization endpoint
- `GET /auth/callback` → exchange code → get token → store in Flask session
- `GET /logout` → clear session → redirect to login

### Role detection:
```
JWT claims → inspect `groups` field (list of strings)
If OIDC_ADMIN_GROUP in groups → session['is_admin'] = True
Else → session['is_admin'] = False
```

### Route protection:
- All routes except `/login` and `/auth/callback` require login
- `/admin/*` routes require `session['is_admin'] == True`
- Use decorators: `@login_required` and `@admin_required`

### Session stores:
```
session['user_id']     # sub claim from JWT
session['user_name']   # name or preferred_username
session['user_email']  # email
session['is_admin']    # bool
```

---

## 4. Database — SQLite

**File:** `/jobs/kitab.db` (inside mounted volume)

### Schema — `jobs` table:

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,       -- UUID4
    user_id     TEXT NOT NULL,          -- OIDC sub
    user_name   TEXT,
    title       TEXT,                   -- book title (user input)
    lang_hint   TEXT,                   -- 'bn', 'ar', 'en', 'mixed'
    status      TEXT DEFAULT 'QUEUED',  -- QUEUED | PROCESSING | OCR_DONE | CLEANING | DONE | FAILED
    page_total  INTEGER DEFAULT 0,
    page_done   INTEGER DEFAULT 0,
    error_msg   TEXT,
    created_at  TEXT,                   -- ISO8601
    updated_at  TEXT
);
```

### `db.py` must provide:
- `init_db()` — create table if not exists
- `create_job(id, user_id, user_name, title, lang_hint)` → insert row
- `get_job(id)` → dict
- `get_jobs_by_user(user_id)` → list of dicts
- `get_all_jobs()` → list of dicts (admin)
- `update_status(id, status, page_done=None, error_msg=None)`

---

## 5. Upload Route

**Route:** `POST /upload`

### Form fields:
- `file` — PDF (required)
- `title` — book title (required)
- `lang_hint` — select: `bn` / `ar` / `en` / `mixed` (default: `bn`)

### Validation:
- File must be `.pdf`
- File size ≤ `MAX_UPLOAD_MB` MB
- Return error flash if invalid

### On success:
1. Generate `job_id = uuid4()`
2. Create `/jobs/{job_id}/` directory
3. Save PDF as `/jobs/{job_id}/input.pdf`
4. Write `/jobs/{job_id}/meta.json`:
```json
{
  "job_id": "",
  "title": "",
  "lang_hint": "",
  "user_id": "",
  "user_name": "",
  "created_at": ""
}
```
5. Insert job row in DB via `create_job()`
6. Enqueue Celery task: `run_pipeline.delay(job_id)`
7. Redirect to `/jobs/{job_id}`

---

## 6. Celery Task — `tasks.py`

**Task:** `run_pipeline(job_id)`

### Steps:
```
1. update_status(job_id, 'PROCESSING')
2. call ocr.run(job_id)              → fills /jobs/{job_id}/pages/
3. update_status(job_id, 'OCR_DONE')
4. call cleaner.merge(job_id)        → writes output.txt + output.html
5. update_status(job_id, 'CLEANING')
6. update_status(job_id, 'DONE')
```

On any exception:
```
update_status(job_id, 'FAILED', error_msg=str(e))
```

### Config:
- `task_soft_time_limit = 3600` (1 hour)
- `task_time_limit = 7200` (2 hour hard kill)
- `worker_prefetch_multiplier = 1` (one job at a time, CPU mode)

---

## 7. OCR Module — `ocr.py`

**Library:** `surya-ocr`

### `run(job_id)`:
1. Read `/jobs/{job_id}/input.pdf`
2. Convert PDF pages to images (use `pdf2image`)
3. Load Surya OCR model (CPU mode, `SURYA_CPU_ONLY=true`)
4. For each page image:
   - Run Surya OCR → get text + bounding boxes
   - Write `/jobs/{job_id}/pages/page_{n:03d}.txt`
   - Write `/jobs/{job_id}/pages/page_{n:03d}.html` (basic HTML with `<p>` per text block)
   - Call `update_status(job_id, 'PROCESSING', page_done=n)`
5. Write `page_total` to DB after PDF loaded

### Language hints → Surya langs:
```python
LANG_MAP = {
    'bn': ['bn'],
    'ar': ['ar'],
    'en': ['en'],
    'mixed': ['bn', 'ar', 'en'],
}
```

### HTML per page format:
```html
<div class="page" data-page="1">
  <p>text block 1</p>
  <p>text block 2</p>
</div>
```

---

## 8. Cleaner Module — `cleaner.py`

### `merge(job_id)`:
1. Read all `page_*.txt` in order from `/jobs/{job_id}/pages/`
2. Concatenate → write `/jobs/{job_id}/output.txt`
3. Read all `page_*.html` in order
4. Wrap in full HTML document → write `/jobs/{job_id}/output.html`

### `output.html` wrapper:
```html
<!DOCTYPE html>
<html lang="bn" dir="auto">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body { font-family: serif; max-width: 800px; margin: auto; padding: 2rem; }
    .page { margin-bottom: 2rem; border-bottom: 1px solid #ccc; }
    p { line-height: 2; }
  </style>
</head>
<body>
  {all page divs concatenated}
</body>
</html>
```

---

## 9. Job Status Page — `/jobs/{job_id}`

### Show:
- Job title, lang, created time
- Status badge (Flowbite badge component, color by status)
- Progress bar: `page_done / page_total` (Flowbite progress)
- If DONE: download buttons for `output.txt` and `output.html`
- If DONE: "Preview HTML" button → opens `/jobs/{job_id}/preview`
- If FAILED: red error message + retry button
- Auto-refresh every 5 seconds via `<meta http-equiv="refresh">` until DONE or FAILED

### Status badge colors:
```
QUEUED      → gray
PROCESSING  → blue
OCR_DONE    → indigo
CLEANING    → yellow
DONE        → green
FAILED      → red
```

---

## 10. Download Routes

```
GET /jobs/{job_id}/download/txt   → serve output.txt
GET /jobs/{job_id}/download/html  → serve output.html
GET /jobs/{job_id}/preview        → render output.html in iframe page
```

- Check job belongs to `session['user_id']` OR `session['is_admin']` before serving
- 403 if unauthorized

---

## 11. Dashboard — `/dashboard`

### Regular user:
- Table of own jobs (Flowbite table)
- Columns: Title | Lang | Status | Pages | Created | Actions
- Actions: View | Download (if DONE)

### Admin:
- Same table but ALL jobs
- Extra column: Uploaded By

---

## 12. UI — Flowbite + Tailwind

- Load via CDN in `base.html`:
```html
<link href="https://cdn.jsdelivr.net/npm/flowbite@2/dist/flowbite.min.css" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/flowbite@2/dist/flowbite.min.js"></script>
```
- Navbar: app name + user name + logout button
- Flowbite components to use:
  - `Table` → job lists
  - `Badge` → status
  - `Progress` → job progress
  - `Dropzone` → PDF upload
  - `Alert` → flash messages
  - `Button` → all actions
  - `Stepper` (optional) → job state steps

---

## 13. Docker Compose

### Services:
```yaml
services:
  redis:
    image: redis:7-alpine

  web:
    build:
      context: .
      dockerfile: Dockerfile.web
    ports:
      - "5000:5000"
    env_file: .env
    volumes:
      - ./jobs:/jobs
    depends_on:
      - redis

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    env_file: .env
    volumes:
      - ./jobs:/jobs
    depends_on:
      - redis
```

---

## 14. Dockerfiles

### `Dockerfile.web`:
- Base: `python:3.12-slim`
- Install: `uv`
- Copy `web/` + `pyproject.toml`
- `uv sync`
- CMD: `gunicorn -w 2 -b 0.0.0.0:5000 web.app:app`

### `Dockerfile.worker`:
- Base: `python:3.12-slim`
- Install: system deps for `pdf2image` (`poppler-utils`)
- Install: `uv`
- Copy `worker/` + `pyproject.toml`
- `uv sync`
- CMD: `celery -A worker.celery_app worker --loglevel=info --concurrency=1`

---

## 15. `pyproject.toml` Dependencies

```toml
[project]
name = "kitab-pipeline"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
  "flask",
  "authlib",
  "celery",
  "redis",
  "python-dotenv",
  "surya-ocr",
  "pdf2image",
  "gunicorn",
  "requests",
]
```

---

## 16. What Agent Must NOT Do

- Do not use SQLAlchemy or any ORM — raw `sqlite3` only
- Do not use `flask-login` — session management is manual via OIDC
- Do not use JavaScript frameworks — Jinja2 + Flowbite only
- Do not skip `.env` loading — every config value comes from env
- Do not hardcode paths — use `JOBS_DIR` env var everywhere
- Do not add EPUB logic — that is phase 2

---

## 17. Deliverable Checklist

Agent must produce all of the following before done:

- [ ] All files in folder structure exist and are non-empty
- [ ] `.env.example` committed with all keys
- [ ] OIDC login → callback → session → logout works end to end
- [ ] Upload PDF → job created → task enqueued
- [ ] Celery worker picks up task → runs Surya OCR → writes page files
- [ ] Merger writes `output.txt` + `output.html`
- [ ] Status page shows live progress (auto-refresh)
- [ ] Download routes work with auth check
- [ ] Admin sees all jobs, regular user sees own only
- [ ] Docker Compose `up` starts all 3 services cleanly