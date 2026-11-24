"""
search_engine.py — Pencarian relevansi menggunakan BM25.

BM25 (Best Match 25) adalah algoritma ranking dokumen yang mempertimbangkan:
- Frekuensi kata dalam dokumen (term frequency)
- Kelangkaan kata di seluruh korpus (inverse document frequency)
- Panjang dokumen (normalisasi)
"""
import re
from typing import List, Tuple
from rank_bm25 import BM25Okapi


def tokenize(text: str) -> List[str]:
    """
    Ubah teks menjadi daftar kata (token).
    Huruf kecil semua, tanda baca dihapus.
    Contoh: "Apa itu rekursi?" -> ["apa", "itu", "rekursi"]
    """
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    return text.split()


def search_questions(query: str, questions: List[dict]) -> List[Tuple[dict, float]]:
    """
    Cari pertanyaan yang paling relevan dengan query menggunakan BM25.

    Parameters
    ----------
    query     : kata kunci pencarian dari user
    questions : list dict pertanyaan, setiap dict punya key: title, body, topic_tag

    Returns
    -------
    List of (question_dict, score) diurutkan dari skor tertinggi.
    Jika query kosong atau tidak ada pertanyaan, kembalikan semua dengan skor 0.
    """
    if not questions or not query.strip():
        return [(q, 0.0) for q in questions]

    corpus = []
    for q in questions:
        combined = f"{q.get('title', '')} {q.get('body', '')} {q.get('topic_tag', '')}"
        corpus.append(tokenize(combined))

    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize(query))

    scored = list(zip(questions, scores))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
