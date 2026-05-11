# Election Intelligence — Deployment Guide

A Flask-based field intelligence platform for elections: voter roll ingestion (PDF/OCR), ward analytics, role-based access for candidates / managers / booth agents / karyakartas, family graphs, slip & packet PDFs, and a PWA dashboard.

---

## 1. What's in the package

| File | Purpose |
|---|---|
| `Dockerfile` | Production container image (Python 3.12-slim + Tesseract). |
| `docker-compose.yml` | One-command deploy with persisted volumes. |
| `requirements.txt` | Pinned Python dependencies. |
| `wsgi.py` | gunicorn / uWSGI entrypoint. |
| `.env.example` | Template for runtime configuration. |
| `.dockerignore` / `.gitignore` | Keep DB, uploads, secrets out of images. |
| `deploy/nginx.conf` | Sample HTTPS reverse-proxy config. |
| `deploy/election-intel.service` | systemd unit for bare-metal installs. |

---

## 2. Quick start (Docker — recommended)

```bash
git clone <your-repo> election_intel
cd election_intel
cp .env.example .env
# EDIT .env — at minimum set EI_SECRET_KEY to a long random string
docker compose up -d --build
```

App is now at `http://<server>:5001`.

Default login: **`admin` / `admin123`** — change immediately via the dashboard or with `auth.set_user_password()`.

### Volumes

`docker-compose.yml` mounts these from the host so they survive redeploys:

- `./election_intel.db` — SQLite database (users, tags, audit, voter overrides)
- `./saved_wards/` — JSON snapshots of imported wards
- `./uploads/` — raw PDFs uploaded for parsing

Back these up nightly (`tar czf backup-$(date +%F).tgz election_intel.db saved_wards uploads`).

---

## 3. Bare-metal install (Ubuntu 22.04+)

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv tesseract-ocr tesseract-ocr-eng \
                    libgl1 libglib2.0-0 nginx

sudo mkdir -p /opt/election_intel /var/log/election_intel
sudo chown $USER:$USER /opt/election_intel /var/log/election_intel
git clone <your-repo> /opt/election_intel
cd /opt/election_intel

python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
# edit .env — set EI_SECRET_KEY

sudo cp deploy/election-intel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now election-intel

sudo cp deploy/nginx.conf /etc/nginx/sites-available/election-intel
sudo ln -s /etc/nginx/sites-available/election-intel /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

For TLS use `certbot --nginx -d your-domain.example.com`.

---

## 4. Environment variables

| Var | Default | Notes |
|---|---|---|
| `EI_SECRET_KEY` | `dev-secret` (insecure) | **Required in production.** Used to sign JWTs. |
| `EI_HOST` | `127.0.0.1` | Bind address (only honored by `python app.py`; gunicorn uses `--bind`). |
| `EI_PORT` | `5001` | |
| `EI_DEBUG` | `1` | Set `0` in production. |
| `DATABASE_URL` | `sqlite:///election_intel.db` | Set to `postgresql://…` for Postgres (uncomment driver in `requirements.txt`). |
| `WHATSAPP_PROVIDER` | _(unset)_ | `meta`, `twilio`, or `mock`. |
| `WHATSAPP_API_TOKEN`, `WHATSAPP_PHONE_ID` | | Meta Cloud API credentials. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | | Twilio credentials. |

---

## 5. OCR backends

PDF text extraction uses **PyMuPDF** (always works, no setup).

When a PDF is image-only the parser falls back to OCR:

- **Linux/Docker** → Tesseract (installed in the image, `pytesseract` driver). Slower (~3–5 s/page) but free and portable.
- **Windows dev machines** → install `winocr` (`pip install winocr`) for native ~0.6 s/page OCR. The parser auto-detects it.

If neither backend is available the parser raises `RuntimeError` with a clear message — text-based PDFs continue to work.

---

## 6. Roles & default workflows

| Role | Sees | Can do |
|---|---|---|
| `admin` | Everything | Manage users, tags, hierarchy; full audit; set assignments. |
| `candidate` | All wards/voters in scope | Read-only dashboards + reports. |
| `manager` | Assigned wards | Edit voters, run pipelines, generate reports. |
| `booth_agent` | Assigned booths | Mark consent / surveys; export slips. |
| `karyakarta` | Assigned pages within booths | Door-to-door updates; "My Pages" tab; download own packet PDF. |

The first boot seeds `admin / admin123` only — create the rest via Admin → Users.

---

## 7. Health & monitoring

- `GET /api/status` — JSON heartbeat (used by Docker healthcheck).
- `GET /api/audit?...` — filterable audit log (admin-only).
- `gunicorn` logs to stdout (Docker) or `/var/log/election_intel/` (systemd).

---

## 8. Backup & restore

```bash
# Backup
tar czf ei-backup-$(date +%F).tgz election_intel.db saved_wards uploads

# Restore
tar xzf ei-backup-YYYY-MM-DD.tgz
docker compose restart   # or: sudo systemctl restart election-intel
```

---

## 9. Upgrade

```bash
git pull
docker compose up -d --build         # Docker
# or, bare-metal:
.venv/bin/pip install -r requirements.txt
sudo systemctl restart election-intel
```

Schema migrations run automatically on boot (`database._migrate_schema()`).

---

## 10. Security checklist

- [ ] `.env` has a strong `EI_SECRET_KEY` (≥ 32 random chars).
- [ ] Default `admin` password changed.
- [ ] HTTPS enforced via nginx + Let's Encrypt.
- [ ] `client_max_body_size 60M` matches your largest PDF.
- [ ] Backups scheduled (cron / systemd timer).
- [ ] Server firewall: only 80/443 exposed publicly; 5001 bound to localhost.
- [ ] Database file owned by the app user, mode `600`.
