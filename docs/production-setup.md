# Production Setup Guide

This guide covers deploying LitFlow on a Linux server with Docker Compose, a reverse proxy (Caddy or Nginx), and TLS. It assumes you already have:

- A Linux server (Ubuntu 22.04+ recommended)
- A domain name pointing to the server's public IP
- [Docker Engine](https://docs.docker.com/engine/install/) and [Docker Compose plugin](https://docs.docker.com/compose/install/) installed
- Pocket ID (or another OIDC provider) already running and reachable

---

## Architecture Overview

```
Internet
   │
   ▼
[Caddy / Nginx]  ← TLS termination, reverse proxy
   │
   ├──→ :5000  [LitFlow Web]  (Gunicorn, 2 workers)
   │
   └── internal Docker network
           │
           ├── [Redis]   ← task queue
           └── [Worker]  ← Celery, Surya OCR, CPU-only
```

All services run in the same Docker Compose stack. Only the web service is exposed externally, via the reverse proxy.

---

## 1. Clone the Repository

```bash
git clone https://github.com/your-org/litflow.git
cd litflow
```

---

## 2. Create the `.env` File

```bash
cp .env.example .env
nano .env
```

Fill in every value:

```env
# Pocket-ID OIDC
OIDC_CLIENT_ID=litflow
OIDC_CLIENT_SECRET=<from-pocket-id>
OIDC_DISCOVERY_URL=https://id.example.com/.well-known/openid-configuration
OIDC_REDIRECT_URI=https://litflow.example.com/auth/callback

# JWT Role
OIDC_ADMIN_GROUP=admin

# Flask
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_hex(32))">
BASE_URL=https://litflow.example.com

# Redis
REDIS_URL=redis://redis:6379/0

# Storage
JOBS_DIR=/jobs
MAX_UPLOAD_MB=500

# Surya
SURYA_CPU_ONLY=true
```

> Keep `.env` out of version control. It is already in `.gitignore`.

### Generate a strong SECRET_KEY

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 3. Create the Jobs Volume Directory

```bash
mkdir -p jobs
chmod 755 jobs
```

Docker Compose mounts `./jobs` into both the `web` and `worker` containers at `/jobs`. This directory holds the SQLite database, uploaded PDFs, OCR page output, and final `.txt`/`.html` files.

---

## 4. Build and Start Services

```bash
docker compose up -d --build
```

Check that all three containers are running:

```bash
docker compose ps
```

Expected output:

```
NAME              IMAGE              STATUS          PORTS
litflow-redis-1   redis:7-alpine     Up (healthy)
litflow-web-1     litflow-web        Up              0.0.0.0:5000->5000/tcp
litflow-worker-1  litflow-worker     Up
```

---

## 5. Reverse Proxy Setup

### Option A — Caddy (recommended, automatic TLS)

Install Caddy:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

Edit `/etc/caddy/Caddyfile`:

```caddyfile
litflow.example.com {
    reverse_proxy localhost:5000
}
```

Reload Caddy:

```bash
sudo systemctl reload caddy
```

Caddy automatically provisions and renews a Let's Encrypt TLS certificate.

---

### Option B — Nginx + Certbot

Install:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

Create `/etc/nginx/sites-available/litflow`:

```nginx
server {
    listen 80;
    server_name litflow.example.com;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Large file uploads
        client_max_body_size 512M;
        proxy_read_timeout   3600;
        proxy_send_timeout   3600;
    }
}
```

Enable the site and obtain a certificate:

```bash
sudo ln -s /etc/nginx/sites-available/litflow /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d litflow.example.com
```

Certbot auto-renews the certificate via a systemd timer.

---

## 6. Firewall Rules

Only expose ports 80 and 443. Docker port 5000 should not be directly reachable from the internet.

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (redirect to HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

> If you used `ports: "5000:5000"` in `docker-compose.yml`, Docker bypasses UFW by default.
> To restrict this, change the web service binding to `127.0.0.1:5000:5000` so it only listens on localhost.

Edit `docker-compose.yml`:

```yaml
  web:
    ports:
      - "127.0.0.1:5000:5000"   # localhost only — reverse proxy handles external traffic
```

Then restart:

```bash
docker compose up -d web
```

---

## 7. Verify the Deployment

1. Open `https://litflow.example.com` in a browser
2. You should be redirected to your OIDC provider login page
3. After login you should land on the dashboard
4. Upload a small PDF and confirm the job completes

Check logs if anything is broken:

```bash
# All services
docker compose logs -f

# Web only
docker compose logs -f web

# Worker only
docker compose logs -f worker
```

---

## 8. Gunicorn Tuning

The default Gunicorn command in `Dockerfile.web` uses 2 workers:

```
gunicorn -w 2 -b 0.0.0.0:5000 web.app:app
```

For a production server, increase workers based on CPU cores (`2 × cores + 1` is the standard formula). Override via `docker-compose.yml`:

```yaml
  web:
    command: gunicorn -w 5 -b 0.0.0.0:5000 --timeout 120 web.app:app
```

---

## 9. Worker Tuning

The Celery worker uses `--concurrency=1` (one OCR job at a time) because Surya runs in CPU-only mode and is compute-intensive. Do not increase concurrency unless you have enough RAM and CPU headroom.

For very large books (500+ pages), the worker has a soft time limit of 1 hour and a hard kill at 2 hours (configured in `worker/tasks.py`). Adjust if needed.

---

## 10. Persistent Data & Backups

All runtime data lives in `./jobs/` on the host:

| Path | Contents |
|---|---|
| `jobs/kitab.db` | SQLite database — all job records |
| `jobs/<job-id>/input.pdf` | Original uploaded PDF |
| `jobs/<job-id>/pages/` | Per-page OCR output |
| `jobs/<job-id>/output.txt` | Final merged plain text |
| `jobs/<job-id>/output.html` | Final merged HTML |

### Simple backup script

```bash
#!/bin/bash
# backup-litflow.sh
DEST=/backups/litflow
DATE=$(date +%Y-%m-%d)
mkdir -p "$DEST"
tar -czf "$DEST/jobs-$DATE.tar.gz" ./jobs/
find "$DEST" -name "*.tar.gz" -mtime +30 -delete   # keep 30 days
```

Schedule via cron:

```bash
crontab -e
# Add:
0 3 * * * /home/user/litflow/backup-litflow.sh
```

---

## 11. Updates and Redeployment

```bash
git pull
docker compose up -d --build
```

This rebuilds only the layers that changed. The `./jobs` volume is untouched during redeployment.

To restart a single service without rebuilding:

```bash
docker compose restart web
docker compose restart worker
```

---

## 12. Monitoring

### View running tasks

```bash
docker compose exec worker celery -A worker.celery_app inspect active
```

### Check queued tasks

```bash
docker compose exec worker celery -A worker.celery_app inspect reserved
```

### Redis health

```bash
docker compose exec redis redis-cli ping
# PONG
```

---

## Troubleshooting

### Web container exits immediately

```bash
docker compose logs web
```

Common causes:
- Missing or malformed `.env` (a required key is empty)
- `SECRET_KEY` not set
- OIDC discovery URL unreachable at startup

### Worker never picks up jobs

```bash
docker compose logs worker
```

Common causes:
- `REDIS_URL` mismatch between `web` and `worker`
- Worker container crashed (check for import errors from Surya/pdf2image)

### Upload fails with `413 Request Entity Too Large`

Nginx's default `client_max_body_size` is 1 MB. Make sure the Nginx config includes:

```nginx
client_max_body_size 512M;
```

Then reload Nginx:

```bash
sudo systemctl reload nginx
```

### Jobs stuck in `PROCESSING` forever

The worker may have crashed mid-job. Check:

```bash
docker compose logs worker --tail=100
```

Restart the worker:

```bash
docker compose restart worker
```

The job will remain in `PROCESSING` state in the database. You can manually reset it to `FAILED` via the SQLite CLI:

```bash
docker compose exec web sqlite3 /jobs/kitab.db \
  "UPDATE jobs SET status='FAILED', error_msg='manually reset' WHERE status='PROCESSING';"
```
