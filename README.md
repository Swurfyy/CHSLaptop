# CHS Laptop Form (Self-Hosted)

Eigen beheer alternatief voor FormSubmit, met:
- verplichte handtekening als PNG
- schadefoto verplicht bij `Nee`, optioneel bij `Ja`
- beide bestanden als mailbijlage
- lokale opslag + SQLite logging

## 1) Lokaal starten

1. Python 3.11+ installeren
2. In projectmap:
   - `python -m venv .venv`
   - Windows: `.venv\Scripts\activate`
   - Linux: `source .venv/bin/activate`
   - `pip install -r requirements.txt`
3. `.env.example` kopieren naar `.env` en invullen
4. Start:
   - `uvicorn app:app --reload --host 127.0.0.1 --port 8000`
5. Open:
   - `http://127.0.0.1:8000`

## 2) Vereiste .env variabelen

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_USE_TLS`
- `MAIL_FROM`
- `MAIL_TO`
- `MAIL_SUBJECT_PREFIX`
- `MAX_UPLOAD_MB`

## 3) Productie deploy op Ubuntu VM

1. Plaats project op `/opt/chs-laptop`
2. Maak venv en installeer dependencies:
   - `python3 -m venv /opt/chs-laptop/.venv`
   - `source /opt/chs-laptop/.venv/bin/activate`
   - `pip install -r /opt/chs-laptop/requirements.txt`
3. Zet `.env` in `/opt/chs-laptop/.env`
4. Systemd service:
   - kopieer `deploy/chs-laptop.service` naar `/etc/systemd/system/chs-laptop.service`
   - `sudo systemctl daemon-reload`
   - `sudo systemctl enable --now chs-laptop`
5. Nginx:
   - kopieer `deploy/nginx-chs-laptop.conf` naar `/etc/nginx/sites-available/chs-laptop`
   - symlink naar `sites-enabled`
   - `sudo nginx -t && sudo systemctl reload nginx`

## 4) Data & logs

- Uploads: `storage/uploads/`
- Database: `storage/db/submissions.db`
- Service logs: `journalctl -u chs-laptop -f`

## 5) Functionele checks

- Kies `Nee` zonder schadefoto -> moet blokkeren
- Kies `Nee` met schadefoto -> moet verzenden
- Kies `Ja` zonder schadefoto -> moet verzenden
- Handtekening altijd verplicht
- Mail moet handtekening + (indien gekozen) schadefoto als bijlage bevatten
