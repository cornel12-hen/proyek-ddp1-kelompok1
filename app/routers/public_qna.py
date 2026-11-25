"""
public_qna.py
-------------
Router untuk Forum Publik (Public QnA):
- GET  /qna                      → Feed semua pertanyaan publik (+ search)
- GET  /qna/ask                  → Formulir pertanyaan baru
- POST /qna/ask                  → Simpan pertanyaan baru
- GET  /qna/{question_id}        → Detail thread (pertanyaan + semua jawaban)
- POST /qna/{question_id}/reply  → Tambah jawaban ke thread
- POST /qna/upvote               → Toggle upvote (HTMX endpoint)
"""

import json
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import PublicQuestion, PublicReply, Upvote, TargetType, User
from app.services.search_engine import search_questions
from app.services.identity_service import generate_alias

router = APIRouter(prefix="/qna", tags=["Public QnA"])
templates = Jinja2Templates(directory="app/templates")


def _get_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


def _display_name(author: User, is_anonymous: bool) -> str:
    """Resolve display name for public feed (no space anonymity mode here)."""
    if is_anonymous:
        return author.anonymous_alias or generate_alias(author.id)
    return f"{author.full_name} ({author.batch_year})"


# ─────────────────────────────────────────────
# FEED
# ─────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def qna_feed(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Tampilkan feed pertanyaan publik, dengan pencarian BM25 jika ada query."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Take all the question
    all_questions = db.query(PublicQuestion).order_by(PublicQuestion.created_at.desc()).all()

    # SPrepare the data for template
    questions_data = []
    for ques in all_questions:
        author = db.query(User).filter(User.id == ques.author_id).first()
        display = _display_name(author, ques.is_anonymous) if author else "Pengguna Tidak Dikenal"
        reply_count = db.query(PublicReply).filter(PublicReply.question_id == ques.id).count()

        # Cek apakah user sudah upvote
        has_upvoted = db.query(Upvote).filter(
            Upvote.user_id == user.id,
            Upvote.target_type == TargetType.QUESTION,
            Upvote.target_id == ques.id,
        ).first() is not None

        questions_data.append({
            "id": ques.id,
            "title": ques.title,
            "body": ques.body[:200] + ("..." if len(ques.body) > 200 else ""),
            "topic_tag": ques.topic_tag,
            "display_name": display,
            "upvote_count": ques.upvote_count,
            "has_upvoted": has_upvoted,
            "reply_count": reply_count,
            "created_at": ques.created_at,
        })

    # BM25 search if there is query
    if q.strip():
        scored = search_questions(q, questions_data)
        # Filter out zero-score results when there's a query
        questions_data = [item for item, score in scored if score > 0]
        if not questions_data and q.strip():
            # If nothing matched, show all sorted by relevance anyway
            questions_data = [item for item, score in scored]

    return templates.TemplateResponse("public_qna/feed.html", {
        "request": request,
        "session_user": user,
        "questions": questions_data,
        "search_query": q,
    })


# ─────────────────────────────────────────────
# ASK A QUESTION
# ─────────────────────────────────────────────

@router.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request, db: Session = Depends(get_db)):
    """Formulir untuk mengajukan pertanyaan baru."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("public_qna/ask.html", {
        "request": request, "session_user": user
    })


@router.post("/ask", response_class=HTMLResponse)
def ask_submit(
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    topic_tag: str = Form(""),
    is_anonymous: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Simpan pertanyaan baru ke database."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    question = PublicQuestion(
        author_id=user.id,
        title=title.strip(),
        body=body.strip(),
        topic_tag=topic_tag.strip() or None,
        is_anonymous=is_anonymous,
        upvote_count=0,
    )
    db.add(question)
    db.commit()
    db.refresh(question)

    return RedirectResponse(url=f"/qna/{question.id}", status_code=302)


# ─────────────────────────────────────────────
# THREAD DETAIL
# ─────────────────────────────────────────────

@router.get("/{question_id}", response_class=HTMLResponse)
def thread_detail(question_id: int, request: Request, db: Session = Depends(get_db)):
    """Tampilkan detail thread: pertanyaan + semua jawaban."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    question = db.query(PublicQuestion).filter(PublicQuestion.id == question_id).first()
    if not question:
        return RedirectResponse(url="/qna", status_code=302)

    # Resolve display name untuk pertanyaan
    author = db.query(User).filter(User.id == question.author_id).first()
    q_display = _display_name(author, question.is_anonymous) if author else "Pengguna Tidak Dikenal"

    # Check upvote status for question
    q_upvoted = db.query(Upvote).filter(
        Upvote.user_id == user.id,
        Upvote.target_type == TargetType.QUESTION,
        Upvote.target_id == question.id,
    ).first() is not None

    # Take all the answer
    replies_raw = db.query(PublicReply).filter(
        PublicReply.question_id == question_id
    ).order_by(PublicReply.upvote_count.desc(), PublicReply.created_at.asc()).all()

    replies_data = []
    for rep in replies_raw:
        rep_author = db.query(User).filter(User.id == rep.author_id).first()
        rep_display = _display_name(rep_author, rep.is_anonymous) if rep_author else "Pengguna Tidak Dikenal"
        rep_upvoted = db.query(Upvote).filter(
            Upvote.user_id == user.id,
            Upvote.target_type == TargetType.REPLY,
            Upvote.target_id == rep.id,
        ).first() is not None
        replies_data.append({
            "id": rep.id,
            "body": rep.body,
            "display_name": rep_display,
            "upvote_count": rep.upvote_count,
            "has_upvoted": rep_upvoted,
            "created_at": rep.created_at,
            "is_anonymous": rep.is_anonymous,
        })

    return templates.TemplateResponse("public_qna/thread.html", {
        "request": request,
        "session_user": user,
        "question": question,
        "q_display": q_display,
        "q_upvoted": q_upvoted,
        "replies": replies_data,
    })


# ─────────────────────────────────────────────
# REPLY
# ─────────────────────────────────────────────

@router.post("/{question_id}/reply")
def post_reply(
    question_id: int,
    request: Request,
    body: str = Form(...),
    is_anonymous: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Tambah jawaban ke thread."""
    user = _get_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    question = db.query(PublicQuestion).filter(PublicQuestion.id == question_id).first()
    if not question:
        return RedirectResponse(url="/qna", status_code=302)

    reply = PublicReply(
        question_id=question_id,
        author_id=user.id,
        body=body.strip(),
        is_anonymous=is_anonymous,
        upvote_count=0,
    )
    db.add(reply)
    db.commit()

    return RedirectResponse(url=f"/qna/{question_id}", status_code=302)


# ─────────────────────────────────────────────
# UPVOTE (HTMX)
# ─────────────────────────────────────────────

@router.post("/upvote/{target_type}/{target_id}", response_class=HTMLResponse)
def toggle_upvote(
    target_type: str,
    target_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Toggle upvote on a question or reply.
    Called by HTMX — returns HTML snippet for the upvote button.
    target_type: "question" or "reply"
    """
    user = _get_user(request, db)
    if not user:
        return HTMLResponse('<span class="text-red-500 text-xs">Login diperlukan</span>', status_code=401)

    t_type = TargetType.QUESTION if target_type.upper() == "QUESTION" else TargetType.REPLY

    # Check if already upvoted
    existing = db.query(Upvote).filter(
        Upvote.user_id == user.id,
        Upvote.target_type == t_type,
        Upvote.target_id == target_id,
    ).first()

    if existing:
        # Remove upvote
        db.delete(existing)
        new_count = -1  # Will be adjusted below
        has_upvoted = False
    else:
        # Add upvote
        new_upvote = Upvote(user_id=user.id, target_type=t_type, target_id=target_id)
        db.add(new_upvote)
        new_count = 1
        has_upvoted = True

    # Update the upvote_count on the target
    if t_type == TargetType.QUESTION:
        item = db.query(PublicQuestion).filter(PublicQuestion.id == target_id).first()
    else:
        item = db.query(PublicReply).filter(PublicReply.id == target_id).first()

    if item:
        item.upvote_count = max(0, item.upvote_count + new_count)
        db.commit()
        count = item.upvote_count
    else:
        db.commit()
        count = 0

    # Return HTML snippet for HTMX swap
    btn_class = "text-primary-600 font-semibold" if has_upvoted else "text-slate-500"
    icon = "▲"
    return HTMLResponse(f'''
        <button
            hx-post="/qna/upvote/{target_type}/{target_id}"
            hx-target="this"
            hx-swap="outerHTML"
            class="flex items-center gap-1 text-sm {btn_class} hover:text-primary-600 transition-colors"
        >
            {icon} {count}
        </button>
    ''')