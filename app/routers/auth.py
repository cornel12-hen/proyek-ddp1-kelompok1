import os
import re
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from app.database import get_db
from app.models import User
from app.services.identity_service import generate_alias
from app.services.supabase_client import supabase

router = APIRouter(tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALLOWED_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "")


def _get_user(request: Request, db: Session) -> User | None:
    """Ambil objek User dari sesi aktif. Return None jika belum login."""
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


def _find_or_create_user(db: Session, email: str, full_name: str) -> User:
    """
    Cari user berdasarkan email. Jika belum ada, buat user baru.
    Digunakan setelah Google OAuth berhasil.
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # Username dari bagian lokal email, misal: budi.santoso@ui.ac.id -> budi.santoso
        base_username = email.split("@")[0].replace(".", "_")
        # Pastikan username unik
        username = base_username
        counter = 1
        while db.query(User).filter(User.username == username).first():
            username = f"{base_username}{counter}"
            counter += 1

        user = User(
            username=username,
            email=email,
            full_name=full_name,
            batch_year=0,       # 0 = belum diisi, akan diminta di /profile/setup
            password_hash="",   # tidak dipakai untuk OAuth
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user.anonymous_alias = generate_alias(user.id)
        db.commit()

    return user


# ═══════════════════════════════════════════
# GOOGLE OAUTH
# ═══════════════════════════════════════════

@router.get("/login/google")
def login_google(request: Request):
    """
    Redirect ke halaman login Google via Supabase OAuth.
    Supabase yang mengurus komunikasi dengan Google.
    """
    if not supabase:
        # Supabase belum dikonfigurasi, fallback ke login biasa
        return RedirectResponse(url="/login", status_code=302)

    # URL callback setelah Google selesai — harus sama dengan yang didaftarkan
    # di Google Cloud Console dan Supabase Auth settings
    base_url = str(request.base_url).rstrip("/")
    redirect_url = f"{base_url}/auth/callback"

    response = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {"redirect_to": redirect_url},
    })
    return RedirectResponse(url=response.url)


@router.get("/auth/callback")
def auth_callback(request: Request, code: str = None, error: str = None,
                  db: Session = Depends(get_db)):
    """
    Supabase redirect ke sini setelah Google login selesai.
    Tukar authorization code dengan session, ambil data user, simpan ke DB.
    """
    if error or not code:
        return RedirectResponse(url="/login?error=oauth_failed", status_code=302)

    if not supabase:
        return RedirectResponse(url="/login", status_code=302)

    try:
        # Tukar code dengan session Supabase
        session_data = supabase.auth.exchange_code_for_session({"auth_code": code})
        google_user = session_data.user
    except Exception:
        return RedirectResponse(url="/login?error=oauth_failed", status_code=302)

    email = google_user.email
    full_name = google_user.user_metadata.get("full_name") or email.split("@")[0]

    # Validasi domain email universitas
    if ALLOWED_DOMAIN and not email.endswith(ALLOWED_DOMAIN):
        return RedirectResponse(url=f"/login?error=domain_not_allowed", status_code=302)

    user = _find_or_create_user(db, email, full_name)

    # Simpan ke session cookie
    request.session["user_id"] = user.id

    # Jika angkatan belum diisi (user baru), minta lengkapi profil
    if user.batch_year == 0:
        return RedirectResponse(url="/profile/setup", status_code=302)

    return RedirectResponse(url="/qna", status_code=302)


# ═══════════════════════════════════════════
# SETUP PROFIL (setelah login Google pertama kali)
# ═══════════════════════════════════════════

@router.get("/profile/setup", response_class=HTMLResponse)
def profile_setup_page(request: Request, db: Session = Depends(get_db)):
    """Halaman lengkapi angkatan setelah login Google pertama kali."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.batch_year != 0:
        return RedirectResponse(url="/qna", status_code=302)
    return templates.TemplateResponse("auth/setup.html", {
        "request": request, "session_user": user
    })


@router.post("/profile/setup")
def profile_setup_submit(
    request: Request,
    batch_year: int = Form(...),
    db: Session = Depends(get_db),
):
    """Simpan angkatan user dan redirect ke feed."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (2000 <= batch_year <= 2100):
        return templates.TemplateResponse("auth/setup.html", {
            "request": request, "session_user": user,
            "error": "Tahun angkatan tidak valid."
        })

    user.batch_year = batch_year
    db.commit()
    return RedirectResponse(url="/qna", status_code=302)


# ═══════════════════════════════════════════
# FALLBACK: LOGIN USERNAME + PASSWORD
# (untuk dev lokal / testing tanpa Supabase)
# ═══════════════════════════════════════════

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = None, db: Session = Depends(get_db)):
    """
    Halaman login.
    Jika Supabase dikonfigurasi, tampilkan tombol Google OAuth.
    Jika tidak, tampilkan form username+password.
    """
    if request.session.get("user_id"):
        return RedirectResponse(url="/qna", status_code=302)

    error_messages = {
        "oauth_failed": "Login Google gagal. Coba lagi.",
        "domain_not_allowed": f"Gunakan email universitas ({ALLOWED_DOMAIN}) untuk masuk.",
    }

    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "session_user": None,
        "supabase_enabled": supabase is not None,
        "error": error_messages.get(error, error),
        "allowed_domain": ALLOWED_DOMAIN,
    })


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Proses login username+password (fallback dev lokal)."""
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.password_hash):
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "session_user": None,
            "supabase_enabled": supabase is not None,
            "error": "Username atau password salah.",
            "username": username,
        }, status_code=401)

    request.session["user_id"] = user.id
    return RedirectResponse(url="/qna", status_code=302)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    """
    Halaman register (fallback dev lokal).
    Jika Supabase aktif, sembunyikan halaman ini karena
    registrasi dilakukan otomatis lewat Google OAuth.
    """
    if request.session.get("user_id"):
        return RedirectResponse(url="/qna", status_code=302)
    if supabase:
        # Supabase aktif: tidak perlu register manual
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("auth/register.html", {
        "request": request, "session_user": None
    })


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    full_name: str = Form(...),
    batch_year: int = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Proses registrasi manual (fallback dev lokal)."""
    errors = []

    if not re.match(r'^[a-zA-Z0-9_]{3,50}$', username):
        errors.append("Username hanya boleh huruf, angka, underscore (3-50 karakter).")
    if db.query(User).filter(User.username == username).first():
        errors.append("Username sudah digunakan.")
    if db.query(User).filter(User.email == email).first():
        errors.append("Email sudah terdaftar.")
    if len(password) < 6:
        errors.append("Password minimal 6 karakter.")
    if not (2000 <= batch_year <= 2100):
        errors.append("Tahun angkatan tidak valid.")

    if errors:
        return templates.TemplateResponse("auth/register.html", {
            "request": request, "errors": errors, "session_user": None,
            "form": {"username": username, "email": email,
                     "full_name": full_name, "batch_year": batch_year},
        }, status_code=400)

    new_user = User(
        username=username, email=email, full_name=full_name,
        batch_year=batch_year, password_hash=pwd_context.hash(password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    new_user.anonymous_alias = generate_alias(new_user.id)
    db.commit()

    request.session["user_id"] = new_user.id
    return RedirectResponse(url="/qna", status_code=302)


# ═══════════════════════════════════════════
# LOGOUT & PROFIL
# ═══════════════════════════════════════════

@router.get("/logout")
def logout(request: Request):
    """Hapus sesi dan redirect ke halaman login."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    """Halaman profil user yang sedang login."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("auth/profile.html", {
        "request": request, "user": user, "session_user": user
    })