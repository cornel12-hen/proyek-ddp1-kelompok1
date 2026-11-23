import sys, os
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, create_all_tables
from app.models import User, Space, SpaceMember, SpaceResource, SpaceThread, SpaceReply, Quiz, PublicQuestion, PublicReply, AnonymityMode, QuizType
from app.services.identity_service import generate_alias
from passlib.context import CryptContext
import json

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def main():
    create_all_tables()
    db = SessionLocal()

    # Cek apakah sudah pernah di-seed
    if db.query(User).first():
        print("Sudah ada data di database")
        db.close()
        return

    print("Membuat data contoh...")

    # ── Users ──────────────────────────────────────
    users_data = [
        {"username": "cornel_hw", "email": "cornel@ui.ac.id", "full_name": "Cornelius Henry", "batch_year": 2026, "password": "password123"},
        {"username": "hania_az", "email": "hania@ui.ac.id", "full_name": "Hania Aisyatu", "batch_year": 2026, "password": "password123"},
        {"username": "reja_ar", "email": "reja@ui.ac.id", "full_name": "Alfarreza Adiatna", "batch_year": 2026, "password": "password123"},
        {"username": "rahil_r", "email": "rahil@ui.ac.id", "full_name": "Rahil Ramadhan", "batch_year": 2026, "password": "password123"},
        {"username": "burhan_hayo", "email": "burhan@ui.ac.id", "full_name": "Burhan hayuk pal pale", "batch_year": 2020, "password": "password123"},
    ]
    users = []
    for ud in users_data:
        u = User(username=ud["username"], email=ud["email"], full_name=ud["full_name"],
                 batch_year=ud["batch_year"], password_hash=pwd.hash(ud["password"]))
        db.add(u)
        db.commit()
        db.refresh(u)
        u.anonymous_alias = generate_alias(u.id)
        db.commit()
        users.append(u)
        print(f"  User: {u.full_name} ({u.username}) — alias: {u.anonymous_alias}")

    admin = users[0]  # Budi sebagai admin

    # ── Space DDP1 ──────────────────────────────────
    space = Space(title="DDP1 Kelas A 2024", description="Ruang diskusi mahasiswa DDP1 kelas A — materi, kuis, dan tanya jawab.",
                  invite_code="DDP1A1", admin_id=admin.id, anonymity_mode=AnonymityMode.USER_CHOICE)
    db.add(space)
    db.commit()
    db.refresh(space)
    print(f"  Space: {space.title} (kode: {space.invite_code})")

    # Semua user bergabung ke space
    for u in users:
        m = SpaceMember(space_id=space.id, user_id=u.id)
        db.add(m)
    db.commit()

    # ── Resources ──────────────────────────────────
    resources = [
        {"title": "Pengantar Python & Variabel", "content_md": "## Variabel di Python\n\nVariabel adalah wadah untuk menyimpan data.\n\n```python\nnama = 'Budi'\numur = 20\nprint(f'Halo, {nama}! Kamu berumur {umur} tahun.')\n```\n\nPython bersifat **dinamis** — kamu tidak perlu deklarasi tipe data."},
        {"title": "Slide Rekursi (Minggu 5)", "content_md": "## Rekursi\n\nFungsi yang memanggil dirinya sendiri.\n\n```python\ndef faktorial(n):\n    if n == 0:  # base case\n        return 1\n    return n * faktorial(n - 1)  # recursive case\n```", "file_or_link_url": "https://www.cs.cmu.edu/~15110-f12/Unit05PtB-handout.pdf"},
        {"title": "Referensi: Python Official Docs", "file_or_link_url": "https://docs.python.org/3/"},
    ]
    for rd in resources:
        r = SpaceResource(space_id=space.id, title=rd["title"],
                          content_md=rd.get("content_md"), file_or_link_url=rd.get("file_or_link_url"))
        db.add(r)
    db.commit()
    print(f"  {len(resources)} resources ditambahkan")

    # ── Threads & Replies ──────────────────────────
    t1 = SpaceThread(space_id=space.id, author_id=users[2].id,
                     title="Bingung dengan base case rekursi",
                     body="Halo kak, aku bingung kapan harus berhenti rekursi. Kalau lupa base case apa yang terjadi?",
                     is_anonymous=False)
    db.add(t1)
    db.commit()
    db.refresh(t1)

    r1 = SpaceReply(thread_id=t1.id, author_id=admin.id,
                    body="Kalau lupa base case, program akan terus memanggil diri sendiri sampai stack overflow (RecursionError di Python). Base case adalah kondisi BERHENTI rekursi, biasanya kasus paling sederhana yang bisa dijawab langsung tanpa rekursi.",
                    is_anonymous=False)
    db.add(r1)

    t2 = SpaceThread(space_id=space.id, author_id=users[3].id,
                     title="Perbedaan list vs tuple?",
                     body="Kapan kita pakai list dan kapan pakai tuple? Apa bedanya selain mutable/immutable?",
                     is_anonymous=True)
    db.add(t2)
    db.commit()
    print(f"  2 threads diskusi ditambahkan")

    # # ── Quiz Native ───────────────────────────────
    # questions = [
    #     {"question": "Fungsi yang memanggil dirinya sendiri disebut...", "type": "auto",
    #      "answers": [{"option": "Rekursi", "mark": 10}, {"option": "Iterasi", "mark": 0}, {"option": "Polimorfisme", "mark": 0}]},
    #     {"question": "Struktur data Python manakah yang IMMUTABLE?", "type": "auto",
    #      "answers": [{"option": "List", "mark": 0}, {"option": "Tuple", "mark": 10}, {"option": "Dictionary", "mark": 0}, {"option": "Set", "mark": 0}]},
    #     {"question": "Sebutkan 3 kegunaan rekursi dalam pemrograman (essay)!", "type": "auto", "answers": []},
    #     {"question": "Mana yang merupakan tipe data urutan (sequence) di Python?", "type": "auto",
    #      "answers": [{"option": "List", "mark": 5}, {"option": "Tuple", "mark": 5}, {"option": "String", "mark": 5}, {"option": "Integer", "mark": 0}]},
    # ]
    # # Classify & save
    # from app.services.quiz_parser import parse_and_validate_quiz
    # processed = parse_and_validate_quiz(json.dumps(questions))

    # quiz = Quiz(space_id=space.id, title="Kuis Rekursi & Tipe Data",
    #             description="Uji pemahamanmu tentang rekursi dan tipe data Python.",
    #             quiz_type=QuizType.NATIVE, questions_json=json.dumps(processed))
    # db.add(quiz)

    # quiz_ext = Quiz(space_id=space.id, title="Latihan Tambahan di Quizizz",
    #                 description="Kerjakan soal tambahan di Quizizz untuk persiapan UTS.",
    #                 quiz_type=QuizType.EXTERNAL, external_url="https://quizizz.com")
    # db.add(quiz_ext)
    # db.commit()
    # print(f"  2 quiz ditambahkan")

    # ── Public QnA ────────────────────────────────
    public_qs = [
        {"author": users[2], "title": "Kenapa Python pakai indentasi bukan kurung kurawal?", "body": "Di bahasa lain seperti Java ada {}, tapi Python pakai spasi. Kenapa ya? Ada alasan historisnya?", "topic_tag": "Python", "is_anonymous": False},
        {"author": users[3], "title": "Perbedaan == dan is di Python?", "body": "Saya bingung, kadang == dan is memberi hasil yang beda. Kapan pakai yang mana?", "topic_tag": "Python", "is_anonymous": False},
        {"author": users[4], "title": "Cara debug infinite loop di Python?", "body": "Program saya stuck, tidak mau berhenti. Bagaimana cara debug loop yang tidak berakhir?", "topic_tag": "Debugging", "is_anonymous": True},
        {"author": users[1], "title": "Tips belajar algoritma untuk pemula?", "body": "Sebagai senior, ada tips tidak untuk belajar algoritma dari nol? Mulai dari mana yang paling efektif?", "topic_tag": "Tips", "is_anonymous": False},
        {"author": users[0], "title": "Apa itu time complexity O(n)?", "body": "Dosen sempat menyebut Big O notation, tapi belum dijelaskan detail. Bisa tolong jelaskan dengan contoh sederhana?", "topic_tag": "Algoritma", "is_anonymous": False},
    ]
    for pq in public_qs:
        q = PublicQuestion(author_id=pq["author"].id, title=pq["title"], body=pq["body"],
                           topic_tag=pq.get("topic_tag"), is_anonymous=pq["is_anonymous"], upvote_count=0)
        db.add(q)
        db.commit()
        db.refresh(q)

        # Tambah satu reply
        rep = PublicReply(question_id=q.id, author_id=users[(pq["author"].id % 3) + 1].id,
                          body=f"Pertanyaan bagus! Jawabannya bisa ditemukan di dokumentasi resmi Python atau Stack Overflow.",
                          is_anonymous=False, upvote_count=0)
        db.add(rep)
    db.commit()
    print(f"  5 pertanyaan publik + 5 jawaban ditambahkan")

    db.close()
    print("\n[OK] Seed selesai!")
    print("   Jalankan: uvicorn app.main:app --reload")
    print("   Login dengan username yang ada")
    print("   Password semua: password123")
    print(f"   Kode Space DDP1: DDP1A1")

if __name__ == "__main__":
    main()
