# LitFlow

**LitFlow** is a self-hosted web portal for digitising scanned Islamic books. Users upload PDF scans, and the system automatically runs OCR (optical character recognition) on every page, producing clean `.txt` and `.html` outputs ready for editing, search, or publishing.

It is designed to run entirely on-premises — no cloud APIs, no third-party OCR services — using open-source models on CPU hardware.

---

## Current Features (Phase 1)

### 📤 PDF Upload
- Drag-and-drop upload form for scanned book PDFs
- Per-upload metadata: book title and primary language hint (`Bengali`, `Arabic`, `English`, `Mixed`)
- File size validation (configurable limit, default 500 MB)
- Uploaded files stored in a persistent jobs volume (`/jobs`)

### 🔐 Authentication — OIDC via Pocket-ID
- Single sign-on login via any Pocket-ID (OIDC) provider
- No passwords stored — all auth delegated to the identity provider
- Role detection: users in the configured admin group get elevated access
- Session stores user identity, name, email, and admin flag

### ⚙️ Async OCR Pipeline
- PDF pages converted to images via `pdf2image` (Poppler)
- OCR performed by **Surya OCR** — an open-source, multilingual model running in CPU mode
- Language-aware: hints guide Surya to load the right script models (`bn`, `ar`, `en`, or all three for mixed books)
- Each page produces an individual `.txt` fragment and an `.html` fragment with one `<p>` per text block
- All processing happens asynchronously via **Celery + Redis** — the web server is never blocked

### 📊 Live Job Status
- Status page auto-refreshes every 5 seconds while a job is in progress
- Visual progress bar showing pages completed vs. total
- Status lifecycle with colour-coded badges:

  | Status | Colour |
  |---|---|
  | QUEUED | Gray |
  | PROCESSING | Blue |
  | OCR_DONE | Indigo |
  | CLEANING | Yellow |
  | DONE | Green |
  | FAILED | Red |

- Full error message displayed if a job fails

### 📥 Output & Download
- `output.txt` — all pages concatenated as plain text
- `output.html` — full HTML document with per-page `<div>` sections, serif font, RTL/auto direction, ready to open in any browser
- In-app HTML preview via a full-viewport iframe
- Downloads restricted to the job owner or admins (403 otherwise)

### 👤 Dashboard
- Personal job list: title, language, status, page count, created time, and action links
- Admins see all jobs from all users, plus an "Uploaded By" column

### 🛠️ Admin Panel
- Dedicated `/admin/jobs` view listing every job in the system
- Access gated behind OIDC group membership — no separate password

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask (Python 3.12) |
| Auth | Authlib + Pocket-ID (OIDC) |
| Database | SQLite via raw `sqlite3` (no ORM) |
| Task queue | Celery |
| Message broker | Redis |
| OCR engine | Surya OCR (CPU mode) |
| PDF rendering | pdf2image + Poppler |
| UI | Flowbite + Tailwind CSS (CDN), Jinja2 templates |
| WSGI server | Gunicorn |
| Packaging | `uv` / `pyproject.toml` |
| Deployment | Docker Compose (3 services: `redis`, `web`, `worker`) |

---

## What's Not Yet Built

- **EPUB export** — planned for Phase 2
- Post-OCR text cleaning / diacritic normalisation
- Search across job outputs
- Multi-user job sharing or team workspaces
- GPU/CUDA acceleration for OCR (currently CPU-only)
