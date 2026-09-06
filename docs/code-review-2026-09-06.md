# Code Review — 2026-09-06

Reviewer notes on `master` @ d9e3948. Severity-ordered. No code changed by this review.

Top 3 to fix now: **#1** (guard `update_status` — one WHERE clause, kills the resurrection bug and half of #2), **#5** (commit the lockfile), **#6 + #8** (cookie flags, drop `debug=True`). Everything in LOW is safe to defer.

---

## HIGH

### 1. Cancelled/failed jobs resurrect to DONE
`worker/tasks.py:112` — `merge_job` calls `update_status(job_id, "DONE")` unconditionally. `update_status` (`web/db.py:87`) has no terminal-state guard. The chord callback fires after all `ocr_page` tasks finish regardless of a mid-run FAILED or CANCELLED, clobbering it. Same path for `ocr_page` failure (`tasks.py:93`): siblings keep running, chord still merges.

Fix: guard `update_status` — `WHERE id = ? AND status NOT IN ('DONE', 'FAILED', 'CANCELLED')`.

### 2. Cancel does nothing to running work
`web/routes/jobs.py:203` — `_celery.control.revoke(job_id, ...)`. `job_id` is not a Celery task id. The real task ids (`pipeline.id`, per-page ids) are never persisted, so revoke is a no-op. OCR runs to completion after "cancel", wastes CPU, then bug #1 flips the job back to DONE.

Fix: store the chord id on the job row and revoke that; or accept that cancel is DB-only and rely on the `update_status` guard from #1 to stop the resurrection.

### 3. Preview iframe broken
`web/templates/job_preview.html:26` — iframe `src` points at `jobs.download_html`, which sends `as_attachment=True` (`web/routes/jobs.py:100`). The browser downloads the file instead of rendering it; iframe stays blank.

Fix: add a separate inline route (`as_attachment=False`, `mimetype="text/html"`) for the iframe.

### 4. `split_pages` loads the whole book into RAM
`worker/ocr.py:100` — `convert_from_path(pdf_path, dpi=150)` returns every page as a PIL image at once. A 500-page scan at 150 DPI is multi-GB. The product exists to process large scanned books.

Fix: `convert_from_path(..., output_folder=pages_dir, paths_only=True, fmt="png")`, then iterate over the returned paths.

### 5. `uv.lock` is gitignored
`.gitignore:16` — the Dockerfile runs `uv sync --no-dev`, so the dependency tree is re-resolved fresh on every build. Non-reproducible; breaks silently when an upstream package releases.

Fix: remove `uv.lock` from `.gitignore`, commit it.

---

## MEDIUM

### 6. No CSRF protection, no session cookie flags
POST routes `/upload`, `/jobs/<id>/cancel`, `/jobs/<id>/delete` carry no CSRF token. `create_app` (`web/app.py:16`) sets no `SESSION_COOKIE_SAMESITE` / `_SECURE` / `_HTTPONLY`. The destructive delete route is reachable cross-site.

Fix (lazy): set the three cookie flags in `create_app` — `SAMESITE="Lax"`, `SECURE=True`, `HTTPONLY=True`. Add Flask-WTF CSRF only if forms must be POSTable from other origins (they don't).

### 7. No `.dockerignore`
The build context ships `jobs/` (uploaded PDFs, `kitab.db`) to the Docker daemon on every build.

Fix: add `.dockerignore` — `jobs/`, `.venv/`, `.git/`, `__pycache__/`, `.env`.

### 8. `app.run(debug=True)`
`web/app.py:53` — the Werkzeug debugger is RCE if anyone runs `python web/app.py`. Prod uses gunicorn anyway.

Fix: gate on a `FLASK_DEBUG` env var or drop the arg.

### 9. Cancel status lists disagree
Route allows `("QUEUED", "PROCESSING")` (`web/routes/jobs.py:197`); `cancel_job` allows `("QUEUED", "SPLITTING", "PROCESSING")` (`web/db.py:199`). SPLITTING jobs can't be cancelled via the route.

Fix: keep one list, in `db.py` only.

### 10. SQLite shared over bind mount, no WAL / busy_timeout
Two gunicorn workers plus celery all open `/jobs/kitab.db` (`web/db.py:12`). Default rollback journal, 0 ms busy timeout. Concurrent `increment_page_done` from chord pages produces "database is locked".

Fix: in `_get_conn`, `conn.execute("PRAGMA journal_mode=WAL")` and `conn.execute("PRAGMA busy_timeout=5000")`.

### 11. `increment_page_done` unbounded
`web/db.py:122` — `task_acks_late=True` plus time limits mean a redelivered `ocr_page` double-counts. `progress_pct` (`web/routes/jobs.py:62`) can exceed 100.

Fix: clamp in the UI calc, or `SET page_done = MIN(page_done + 1, page_total)`.

### 12. Output HTML always `lang="bn"`
`worker/cleaner.py:27` — the template hardcodes `lang="bn"` for Arabic / English / mixed books.

Fix: pass `lang_hint` through `merge()`.

---

## LOW — bloat

### 13. `run_pipeline` legacy stub
`worker/tasks.py:125` — comment cites "rolling deploys"; README says Phase 1, pre-first-deploy. Git has the history. Delete it.

### 14. Web image builds torch + surya-ocr
`Dockerfile:15` — `uv sync` in `base`; the web target never runs OCR. ~200 MB of torch plus models in the web image for nothing.

Fix: move OCR deps to an optional group (`[project.optional-dependencies] ocr = [...]`), `uv sync --extra ocr` only in the worker target. Skip if image size isn't hurting yet.

### 15. `load_dotenv()` in 6 modules
`app.py`, `auth.py`, `db.py`, `ocr.py`, `cleaner.py`, `celery_app.py`. Compose already injects env via `env_file`. One call per entrypoint (`app.py`, `celery_app.py`) is enough; drop the other four.

### 16. Manual upload size check duplicates `MAX_CONTENT_LENGTH`
`web/routes/upload.py:71-77` seeks to measure size; `web/app.py:23` already sets `MAX_CONTENT_LENGTH` to the same value and Flask 413s before the handler runs. Delete the manual block.

### 17. `with _get_conn() as conn` doesn't close the connection
sqlite `__exit__` commits the transaction, leaves the connection open until GC. Low traffic, so minor. Use `contextlib.closing(_get_conn())` if you touch it.

### 18. lang_hint read from meta.json in worker
`worker/tasks.py:49` — the `jobs` row already has `lang_hint`. Two sources of truth. Use `get_job(job_id)["lang_hint"]`.

### 19. Downloads `abort(404)` when status != DONE
`web/routes/jobs.py:83` and siblings. Semantically 409; cosmetic.

### 20. Zero tests
Fan-out/fan-in plus `cleaner.merge` (sort order, HTML escaping, empty-page skip) is non-trivial. Add one `test_merge.py`: write two fake `page_*.txt` / `page_*.html`, assert concat order, `&lt;` escaping, and the `output.html` wrapper.
