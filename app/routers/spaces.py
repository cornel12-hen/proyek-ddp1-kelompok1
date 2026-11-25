"""
spaces.py — Router untuk Collaborative Spaces (List, Create, Join, Resource, Discussion, Checkpoint Quiz).
"""
import json
import os
import random
import shutil
import string
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AnonymityMode,
    Quiz,
    QuizSubmission,
    QuizType,
    Space,
    SpaceMember,
    SpaceReply,
    SpaceResource,
    SpaceThread,
    User,
)
from app.services.identity_service import resolve_display_name

router = APIRouter(prefix="/spaces", tags=["spaces"])
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _get_user(request: Request, db: Session) -> Optional[User]:
    """Ambil user yang sedang login dari session. Return None jika belum login."""
    uid = request.session.get("user_id")
    return db.query(User).filter(User.id == uid).first() if uid else None


def _is_member(db: Session, space_id: int, user_id: int) -> bool:
    """Cek apakah user terdaftar sebagai anggota Space."""
    return (
        db.query(SpaceMember)
        .filter(SpaceMember.space_id == space_id, SpaceMember.user_id == user_id)
        .first()
        is not None
    )


def _gen_invite_code(db: Session) -> str:
    """Generate kode undangan 6 karakter alphanumeric unik."""
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        exists = db.query(Space).filter(Space.invite_code == code).first()
        if not exists:
            return code


def _enforce_anon(mode: AnonymityMode, is_anonymous_form: bool, author_id: int, admin_id: int) -> bool:
    """
    Terapkan aturan anonimitas Space ke postingan:
    - OPEN_ONLY  : paksa False (selalu terbuka)
    - ANON_ONLY  : paksa True kecuali admin Space
    - USER_CHOICE: ikuti pilihan user dari form
    """
    if mode == AnonymityMode.OPEN_ONLY:
        return False
    if mode == AnonymityMode.ANON_ONLY:
        return author_id != admin_id
    return is_anonymous_form


def classify_question(answers: list) -> str:
    """
    Klasifikasi otomatis tipe soal berdasarkan jumlah jawaban benar:
    - len(answers) == 0    -> 'ESSAY'
    - count(mark > 0) == 1 -> 'SINGLE_CHOICE'
    - count(mark > 0) > 1  -> 'MULTIPLE_CHOICE'
    """
    if not answers:
        return "ESSAY"
    correct = sum(1 for a in answers if a.get("mark", 0) > 0)
    if correct == 1:
        return "SINGLE_CHOICE"
    elif correct > 1:
        return "MULTIPLE_CHOICE"
    return "SINGLE_CHOICE"


def parse_quiz_json(json_str: str) -> list:
    """
    Parse dan validasi JSON soal quiz.
    Setiap soal ditambahkan field 'classified_type' hasil klasifikasi otomatis.
    Raise ValueError jika format tidak valid.
    """
    questions = json.loads(json_str)
    if not isinstance(questions, list) or len(questions) == 0:
        raise ValueError("Quiz harus berupa array JSON dan minimal berisi 1 soal.")
    for i, q in enumerate(questions):
        if not isinstance(q, dict) or "question" not in q or not str(q["question"]).strip():
            raise ValueError(f"Soal #{i + 1} wajib memiliki field 'question'.")
        answers = q.get("answers", [])
        if not isinstance(answers, list):
            raise ValueError(f"Field 'answers' pada soal #{i + 1} harus berupa array.")
        q["classified_type"] = classify_question(answers)
    return questions


# ---------------------------------------------------------------------------
# Routes: List, Create, Join, Detail Space
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
def list_spaces(request: Request, db: Session = Depends(get_db)):
    """Tampilkan daftar Space yang diikuti oleh user."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    memberships = db.query(SpaceMember).filter(SpaceMember.user_id == user.id).all()
    spaces = [m.space for m in memberships if m.space]

    return templates.TemplateResponse(
        "spaces/list.html",
        {"request": request, "session_user": user, "spaces": spaces},
    )


@router.get("/create", response_class=HTMLResponse)
def create_space_form(request: Request, db: Session = Depends(get_db)):
    """Tampilkan form pembuatan Space baru."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "spaces/create.html",
        {"request": request, "session_user": user, "error": None},
    )


@router.post("/create", response_class=HTMLResponse)
def create_space_submit(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    anonymity_mode: str = Form("USER_CHOICE"),
    db: Session = Depends(get_db),
):
    """Simpan Space baru, buat invite_code 6 karakter, dan daftarkan pembuat sebagai admin & member."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if not title.strip():
        return templates.TemplateResponse(
            "spaces/create.html",
            {"request": request, "session_user": user, "error": "Nama Space wajib diisi."},
        )

    try:
        mode_enum = AnonymityMode(anonymity_mode)
    except ValueError:
        mode_enum = AnonymityMode.USER_CHOICE

    new_space = Space(
        title=title.strip(),
        description=description.strip(),
        invite_code=_gen_invite_code(db),
        admin_id=user.id,
        anonymity_mode=mode_enum,
    )
    db.add(new_space)
    db.commit()
    db.refresh(new_space)

    member = SpaceMember(space_id=new_space.id, user_id=user.id)
    db.add(member)
    db.commit()

    return RedirectResponse(url=f"/spaces/{new_space.id}", status_code=303)


@router.get("/join", response_class=HTMLResponse)
def join_space_form(request: Request, db: Session = Depends(get_db)):
    """Tampilkan form bergabung ke Space melalui kode undangan."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "spaces/join.html",
        {"request": request, "session_user": user, "error": None},
    )


@router.post("/join", response_class=HTMLResponse)
def join_space_submit(
    request: Request,
    invite_code: str = Form(...),
    db: Session = Depends(get_db),
):
    """Proses bergabung ke Space menggunakan kode undangan 6 karakter."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    code_clean = invite_code.strip().upper()
    space = db.query(Space).filter(Space.invite_code == code_clean).first()
    if not space:
        return templates.TemplateResponse(
            "spaces/join.html",
            {"request": request, "session_user": user, "error": "Kode undangan tidak ditemukan."},
        )

    if not _is_member(db, space.id, user.id):
        db.add(SpaceMember(space_id=space.id, user_id=user.id))
        db.commit()

    return RedirectResponse(url=f"/spaces/{space.id}", status_code=303)


@router.get("/{space_id}", response_class=HTMLResponse)
def space_detail(
    space_id: int,
    request: Request,
    tab: str = "resource",
    db: Session = Depends(get_db),
):
    """Tampilkan detail Space dengan 3 tab: resource, discussion, checkpoint."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or not _is_member(db, space.id, user.id):
        return RedirectResponse(url="/spaces", status_code=303)

    resources = (
        db.query(SpaceResource)
        .filter(SpaceResource.space_id == space.id)
        .order_by(SpaceResource.created_at.desc())
        .all()
    )

    raw_threads = (
        db.query(SpaceThread)
        .filter(SpaceThread.space_id == space.id)
        .order_by(SpaceThread.created_at.desc())
        .all()
    )
    threads_data = []
    for t in raw_threads:
        display_name = resolve_display_name(
            author_id=t.author.id,
            full_name=t.author.full_name,
            batch_year=t.author.batch_year,
            alias=t.author.anonymous_alias or f"Anonim #{t.author.id}",
            is_anonymous=t.is_anonymous,
            space_mode=space.anonymity_mode,
            space_admin_id=space.admin_id,
        )
        threads_data.append(
            {
                "id": t.id,
                "title": t.title,
                "body": t.body,
                "display_name": display_name,
                "reply_count": len(t.replies),
                "created_at": t.created_at,
            }
        )

    quizzes = (
        db.query(Quiz)
        .filter(Quiz.space_id == space.id)
        .order_by(Quiz.created_at.desc())
        .all()
    )
    user_submissions = {
        sub.quiz_id: sub
        for sub in db.query(QuizSubmission).filter(QuizSubmission.user_id == user.id).all()
    }

    return templates.TemplateResponse(
        "spaces/detail.html",
        {
            "request": request,
            "session_user": user,
            "space": space,
            "active_tab": tab if tab in ("resource", "discussion", "checkpoint") else "resource",
            "is_admin": space.admin_id == user.id,
            "resources": resources,
            "threads": threads_data,
            "quizzes": quizzes,
            "user_submissions": user_submissions,
        },
    )


# ---------------------------------------------------------------------------
# Routes: Tab Resource
# ---------------------------------------------------------------------------

@router.get("/{space_id}/resources/add", response_class=HTMLResponse)
def add_resource_form(space_id: int, request: Request, db: Session = Depends(get_db)):
    """Form tambah resource materi (khusus admin Space)."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or space.admin_id != user.id:
        return RedirectResponse(url=f"/spaces/{space_id}?tab=resource", status_code=303)

    return templates.TemplateResponse(
        "spaces/resource_add.html",
        {"request": request, "session_user": user, "space": space, "error": None},
    )


@router.post("/{space_id}/resources/add", response_class=HTMLResponse)
def add_resource_submit(
    space_id: int,
    request: Request,
    title: str = Form(...),
    content_md: str = Form(""),
    external_link: str = Form(""),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Simpan resource materi baru beserta file upload jika ada."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or space.admin_id != user.id:
        return RedirectResponse(url=f"/spaces/{space_id}?tab=resource", status_code=303)

    file_or_link_url = external_link.strip() if external_link.strip() else None

    if file and file.filename:
        safe_name = f"space_{space_id}_{random.randint(1000,9999)}_{os.path.basename(file.filename)}"
        dest_path = os.path.join(UPLOAD_DIR, safe_name)
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_or_link_url = f"/static/uploads/{safe_name}"

    resource = SpaceResource(
        space_id=space.id,
        title=title.strip(),
        content_md=content_md.strip(),
        file_or_link_url=file_or_link_url,
    )
    db.add(resource)
    db.commit()

    return RedirectResponse(url=f"/spaces/{space.id}?tab=resource", status_code=303)


# ---------------------------------------------------------------------------
# Routes: Tab Discussion
# ---------------------------------------------------------------------------

@router.get("/{space_id}/threads/new", response_class=HTMLResponse)
def new_thread_form(space_id: int, request: Request, db: Session = Depends(get_db)):
    """Form buat thread diskusi baru di Space."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or not _is_member(db, space.id, user.id):
        return RedirectResponse(url="/spaces", status_code=303)

    return templates.TemplateResponse(
        "spaces/thread_new.html",
        {
            "request": request,
            "session_user": user,
            "space": space,
            "is_admin": space.admin_id == user.id,
        },
    )


@router.post("/{space_id}/threads/new", response_class=HTMLResponse)
def new_thread_submit(
    space_id: int,
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    is_anonymous: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Simpan thread diskusi baru dengan penegakan aturan anonimitas Space."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or not _is_member(db, space.id, user.id):
        return RedirectResponse(url="/spaces", status_code=303)

    final_anon = _enforce_anon(space.anonymity_mode, is_anonymous, user.id, space.admin_id)

    thread = SpaceThread(
        space_id=space.id,
        author_id=user.id,
        title=title.strip(),
        body=body.strip(),
        is_anonymous=final_anon,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    return RedirectResponse(url=f"/spaces/{space.id}/threads/{thread.id}", status_code=303)


@router.get("/{space_id}/threads/{thread_id}", response_class=HTMLResponse)
def thread_detail(
    space_id: int, thread_id: int, request: Request, db: Session = Depends(get_db)
):
    """Tampilkan detail thread diskusi beserta seluruh balasan."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or not _is_member(db, space.id, user.id):
        return RedirectResponse(url="/spaces", status_code=303)

    thread = (
        db.query(SpaceThread)
        .filter(SpaceThread.id == thread_id, SpaceThread.space_id == space.id)
        .first()
    )
    if not thread:
        return RedirectResponse(url=f"/spaces/{space.id}?tab=discussion", status_code=303)

    thread_author_name = resolve_display_name(
        author_id=thread.author.id,
        full_name=thread.author.full_name,
        batch_year=thread.author.batch_year,
        alias=thread.author.anonymous_alias or f"Anonim #{thread.author.id}",
        is_anonymous=thread.is_anonymous,
        space_mode=space.anonymity_mode,
        space_admin_id=space.admin_id,
    )

    replies_data = []
    for r in sorted(thread.replies, key=lambda x: x.created_at):
        r_name = resolve_display_name(
            author_id=r.author.id,
            full_name=r.author.full_name,
            batch_year=r.author.batch_year,
            alias=r.author.anonymous_alias or f"Anonim #{r.author.id}",
            is_anonymous=r.is_anonymous,
            space_mode=space.anonymity_mode,
            space_admin_id=space.admin_id,
        )
        replies_data.append(
            {
                "id": r.id,
                "body": r.body,
                "display_name": r_name,
                "created_at": r.created_at,
            }
        )

    return templates.TemplateResponse(
        "spaces/thread_detail.html",
        {
            "request": request,
            "session_user": user,
            "space": space,
            "thread": thread,
            "thread_author_name": thread_author_name,
            "replies": replies_data,
            "is_admin": space.admin_id == user.id,
        },
    )


@router.post("/{space_id}/threads/{thread_id}/reply", response_class=HTMLResponse)
def reply_thread_submit(
    space_id: int,
    thread_id: int,
    request: Request,
    body: str = Form(...),
    is_anonymous: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Simpan balasan pada thread diskusi Space."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or not _is_member(db, space.id, user.id):
        return RedirectResponse(url="/spaces", status_code=303)

    final_anon = _enforce_anon(space.anonymity_mode, is_anonymous, user.id, space.admin_id)

    reply = SpaceReply(
        thread_id=thread_id,
        author_id=user.id,
        body=body.strip(),
        is_anonymous=final_anon,
    )
    db.add(reply)
    db.commit()

    return RedirectResponse(url=f"/spaces/{space.id}/threads/{thread_id}", status_code=303)


# ---------------------------------------------------------------------------
# Routes: Tab Checkpoint (Quiz)
# ---------------------------------------------------------------------------

@router.get("/{space_id}/quizzes/create", response_class=HTMLResponse)
def create_quiz_form(space_id: int, request: Request, db: Session = Depends(get_db)):
    """Form pembuatan quiz baru (khusus admin Space)."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or space.admin_id != user.id:
        return RedirectResponse(url=f"/spaces/{space_id}?tab=checkpoint", status_code=303)

    sample_json = json.dumps(
        [
            {
                "question": "Apa output dari print(2 ** 3) di Python?",
                "answers": [
                    {"text": "6", "mark": 0},
                    {"text": "8", "mark": 10},
                    {"text": "9", "mark": 0},
                ],
            }
        ],
        indent=2,
    )

    return templates.TemplateResponse(
        "spaces/quiz_create.html",
        {
            "request": request,
            "session_user": user,
            "space": space,
            "error": None,
            "sample_json": sample_json,
        },
    )


@router.post("/{space_id}/quizzes/create", response_class=HTMLResponse)
def create_quiz_submit(
    space_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    quiz_type: str = Form("NATIVE"),
    external_url: str = Form(""),
    questions_json: str = Form(""),
    db: Session = Depends(get_db),
):
    """Simpan quiz baru setelah validasi format JSON soal."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or space.admin_id != user.id:
        return RedirectResponse(url=f"/spaces/{space_id}?tab=checkpoint", status_code=303)

    try:
        q_type_enum = QuizType(quiz_type)
    except ValueError:
        q_type_enum = QuizType.NATIVE

    parsed_json_str = None
    if q_type_enum == QuizType.NATIVE:
        try:
            parsed = parse_quiz_json(questions_json)
            parsed_json_str = json.dumps(parsed)
        except Exception as exc:
            return templates.TemplateResponse(
                "spaces/quiz_create.html",
                {
                    "request": request,
                    "session_user": user,
                    "space": space,
                    "error": f"Format JSON tidak valid: {exc}",
                    "sample_json": questions_json,
                },
            )

    quiz = Quiz(
        space_id=space.id,
        title=title.strip(),
        description=description.strip(),
        quiz_type=q_type_enum,
        external_url=external_url.strip() if q_type_enum == QuizType.EXTERNAL else None,
        questions_json=parsed_json_str,
    )
    db.add(quiz)
    db.commit()

    return RedirectResponse(url=f"/spaces/{space.id}?tab=checkpoint", status_code=303)


@router.get("/{space_id}/quizzes/{quiz_id}", response_class=HTMLResponse)
def take_quiz_page(
    space_id: int, quiz_id: int, request: Request, db: Session = Depends(get_db)
):
    """Halaman pengerjaan quiz oleh anggota Space."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or not _is_member(db, space.id, user.id):
        return RedirectResponse(url="/spaces", status_code=303)

    quiz = db.query(Quiz).filter(Quiz.id == quiz_id, Quiz.space_id == space.id).first()
    if not quiz:
        return RedirectResponse(url=f"/spaces/{space.id}?tab=checkpoint", status_code=303)

    if quiz.quiz_type == QuizType.EXTERNAL and quiz.external_url:
        return RedirectResponse(url=quiz.external_url, status_code=303)

    questions = json.loads(quiz.questions_json) if quiz.questions_json else []
    return templates.TemplateResponse(
        "spaces/quiz_take.html",
        {
            "request": request,
            "session_user": user,
            "space": space,
            "quiz": quiz,
            "questions": questions,
        },
    )


@router.post("/{space_id}/quizzes/{quiz_id}/submit", response_class=HTMLResponse)
async def submit_quiz(
    space_id: int, quiz_id: int, request: Request, db: Session = Depends(get_db)
):
    """Hitung skor pengerjaan quiz dan simpan ke database."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or not _is_member(db, space.id, user.id):
        return RedirectResponse(url="/spaces", status_code=303)

    quiz = db.query(Quiz).filter(Quiz.id == quiz_id, Quiz.space_id == space.id).first()
    if not quiz:
        return RedirectResponse(url=f"/spaces/{space.id}?tab=checkpoint", status_code=303)

    form_data = await request.form()
    questions = json.loads(quiz.questions_json) if quiz.questions_json else []

    total_score = 0.0
    user_answers = {}

    for idx, q in enumerate(questions):
        q_type = q.get("classified_type", classify_question(q.get("answers", [])))
        field_name = f"q_{idx}"
        if q_type == "ESSAY":
            ans_text = form_data.get(field_name, "")
            user_answers[str(idx)] = ans_text
        elif q_type == "MULTIPLE_CHOICE":
            selected_indices = [int(v) for v in form_data.getlist(field_name)]
            user_answers[str(idx)] = selected_indices
            for ans_idx in selected_indices:
                if 0 <= ans_idx < len(q["answers"]):
                    total_score += float(q["answers"][ans_idx].get("mark", 0))
        else:
            val = form_data.get(field_name)
            if val is not None and val != "":
                ans_idx = int(val)
                user_answers[str(idx)] = ans_idx
                if 0 <= ans_idx < len(q["answers"]):
                    total_score += float(q["answers"][ans_idx].get("mark", 0))
            else:
                user_answers[str(idx)] = None

    submission = QuizSubmission(
        quiz_id=quiz.id,
        user_id=user.id,
        answers_json=json.dumps(user_answers),
        total_score=total_score,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    return RedirectResponse(
        url=f"/spaces/{space.id}/quizzes/{quiz.id}/result/{submission.id}",
        status_code=303,
    )


@router.get("/{space_id}/quizzes/{quiz_id}/result/{sub_id}", response_class=HTMLResponse)
def quiz_result_page(
    space_id: int,
    quiz_id: int,
    sub_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Tampilkan hasil pengerjaan dan skor quiz."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    space = db.query(Space).filter(Space.id == space_id).first()
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id, Quiz.space_id == space.id).first()
    submission = (
        db.query(QuizSubmission)
        .filter(QuizSubmission.id == sub_id, QuizSubmission.quiz_id == quiz_id)
        .first()
    )
    if not space or not quiz or not submission:
        return RedirectResponse(url=f"/spaces/{space_id}?tab=checkpoint", status_code=303)

    questions = json.loads(quiz.questions_json) if quiz.questions_json else []
    user_answers = json.loads(submission.answers_json) if submission.answers_json else {}
    max_score = sum(
        sum(max(0.0, float(a.get("mark", 0))) for a in q.get("answers", []))
        for q in questions
    )

    return templates.TemplateResponse(
        "spaces/quiz_result.html",
        {
            "request": request,
            "session_user": user,
            "space": space,
            "quiz": quiz,
            "submission": submission,
            "questions": questions,
            "user_answers": user_answers,
            "max_score": max_score,
        },
    )