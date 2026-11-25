import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from app.database import create_all_tables

SECRET_KEY = os.getenv("SECRET_KEY", "ganti-dengan-string-panjang-acak-sebelum-deploy!")

app = FastAPI(
    title="Collaborative Learning Space",
    description="Platform belajar kolaboratif untuk mahasiswa DDP1",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

os.makedirs("app/static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

from app.routers import auth, public_qna # tambahin spaces di sini
app.include_router(auth.router)
app.include_router(public_qna.router)
# app.include_router(spaces.router)


@app.on_event("startup")
def on_startup():
    create_all_tables()
    db_url = os.getenv("DATABASE_URL", "sqlite (lokal)")
    supabase_url = os.getenv("SUPABASE_URL", "")
    print("[OK] Database siap.")
    print(f"     Mode    : {'PostgreSQL/Supabase' if 'postgresql' in db_url else 'SQLite lokal'}")
    print(f"     Auth    : {'Google OAuth (Supabase)' if supabase_url else 'Username+Password (lokal)'}")
    print("[OK] CLS berjalan di http://127.0.0.1:8000")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/qna")