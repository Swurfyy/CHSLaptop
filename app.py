from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import mimetypes
from contextlib import closing
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import smtplib
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "storage" / "uploads"
DB_DIR = BASE_DIR / "storage" / "db"
DB_PATH = DB_DIR / "submissions.db"
ENV_PATH = BASE_DIR / ".env"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)


def load_dotenv_if_present() -> None:
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


load_dotenv_if_present()

SMTP_HOST = env("SMTP_HOST")
SMTP_PORT = int(env("SMTP_PORT", "587"))
SMTP_USER = env("SMTP_USER")
SMTP_PASS = env("SMTP_PASS")
SMTP_USE_TLS = env("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}
MAIL_FROM = env("MAIL_FROM", SMTP_USER)
MAIL_TO = env("MAIL_TO")
MAIL_SUBJECT_PREFIX = env("MAIL_SUBJECT_PREFIX", "Leenlaptop")
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "10"))

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/heic", "image/heif"}

app = FastAPI(title="CHS Laptop Form")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR)), name="static")
app.mount("/storage/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
logger = logging.getLogger("chs-laptop")


class HealthResponse(BaseModel):
    ok: bool
    timestamp: str


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_db()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                student_name TEXT NOT NULL,
                laptop_number TEXT NOT NULL,
                laptop_ok TEXT NOT NULL,
                damage_evidence_status TEXT NOT NULL,
                signature_status TEXT NOT NULL,
                damage_file_path TEXT,
                signature_file_path TEXT
            )
            """
        )
        conn.commit()


def sanitize(value: str) -> str:
    allowed = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
    return allowed[:80] or "bestand"


async def save_upload(upload: UploadFile | None, prefix: str, student_name: str) -> str | None:
    if upload is None or not upload.filename:
        return None

    content_type = (upload.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Ongeldig bestandstype voor {prefix}.")

    payload = await upload.read()
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    if len(payload) > max_bytes:
        raise HTTPException(status_code=400, detail=f"{prefix} is te groot (max {MAX_UPLOAD_MB}MB).")

    ext = Path(upload.filename).suffix.lower() or ".png"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    safe_student = sanitize(student_name.replace(" ", "-").lower())
    unique = secrets.token_hex(4)
    filename = f"{prefix}-{safe_student}-{stamp}-{unique}{ext}"
    absolute_path = UPLOAD_DIR / filename
    absolute_path.write_bytes(payload)
    return str(absolute_path.relative_to(BASE_DIR))


def send_submission_email(
    student_name: str,
    laptop_number: str,
    laptop_ok: str,
    damage_status: str,
    signature_status: str,
    damage_file_path: str | None,
    signature_file_path: str | None,
) -> None:
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_FROM, MAIL_TO]):
        raise RuntimeError("SMTP config ontbreekt. Vul .env variabelen in.")

    msg = EmailMessage()
    msg["Subject"] = f"{MAIL_SUBJECT_PREFIX} - {student_name}"
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO

    body_lines = [
        "Nieuwe laptop-uitleen bevestiging",
        "",
        f"Student: {student_name}",
        f"Laptop-NR: {laptop_number}",
        f"Laptop in orde: {laptop_ok}",
        f"Schade bewijsfoto: {damage_status}",
        f"Handtekening: {signature_status}",
        "",
        "Bijlagen:",
        f"- Schadefoto: {'ja' if damage_file_path else 'nee'}",
        f"- Handtekening: {'ja' if signature_file_path else 'nee'}",
    ]
    msg.set_content("\n".join(body_lines))

    for rel_path in [damage_file_path, signature_file_path]:
        if not rel_path:
            continue
        file_path = BASE_DIR / rel_path
        if not file_path.exists():
            continue
        data = file_path.read_bytes()
        guessed_type, _ = mimetypes.guess_type(file_path.name)
        maintype, subtype = ("application", "octet-stream")
        if guessed_type and "/" in guessed_type:
            maintype, subtype = guessed_type.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=file_path.name)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", include_in_schema=False)
def read_index() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, timestamp=datetime.now(timezone.utc).isoformat())


@app.post("/submit")
async def submit(
    student_name: str = Form(...),
    laptop_number: str = Form(...),
    laptop_ok: str = Form(...),
    damage_evidence_status: str = Form("Geen bestand toegevoegd"),
    signature_status: str = Form("Bijlage toegevoegd (PNG)"),
    damage_evidence: UploadFile | None = File(None),
    signature_file: UploadFile = File(...),
) -> JSONResponse:
    if laptop_ok not in {"Ja", "Nee"}:
        raise HTTPException(status_code=400, detail="Laptop-status ongeldig.")
    if laptop_ok == "Nee" and damage_evidence is None:
        raise HTTPException(status_code=400, detail="Bewijsfoto is verplicht bij 'Nee'.")

    damage_path = await save_upload(damage_evidence, "schade", student_name)
    signature_path = await save_upload(signature_file, "handtekening", student_name)
    if signature_path is None:
        raise HTTPException(status_code=400, detail="Handtekening ontbreekt.")

    created_at = datetime.now(timezone.utc).isoformat()
    with closing(get_db()) as conn:
        conn.execute(
            """
            INSERT INTO submissions (
                created_at, student_name, laptop_number, laptop_ok,
                damage_evidence_status, signature_status, damage_file_path, signature_file_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                student_name,
                laptop_number,
                laptop_ok,
                damage_evidence_status if damage_path else "Geen bestand toegevoegd",
                signature_status,
                damage_path,
                signature_path,
            ),
        )
        conn.commit()

    try:
        send_submission_email(
            student_name=student_name,
            laptop_number=laptop_number,
            laptop_ok=laptop_ok,
            damage_status=damage_evidence_status if damage_path else "Geen bestand toegevoegd",
            signature_status=signature_status,
            damage_file_path=damage_path,
            signature_file_path=signature_path,
        )
    except Exception as exc:
        logger.exception("Mail verzending mislukt")
        raise HTTPException(status_code=502, detail=f"Mail verzending mislukt: {exc}") from exc

    return JSONResponse({"ok": True, "message": "Bevestiging verzonden."})
