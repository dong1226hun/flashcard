from __future__ import annotations

import random
import re
import sqlite3
from typing import Any

from .caption_labels import FIGURE_TAG_RE
from .db import row_to_dict


DEFAULT_SESSION_SIZE = "all"
MAX_SESSION_SIZE = 100
VALID_RESULTS = {"correct", "wrong", "unsure"}
VALID_SOURCES = {"all", "favorites", "past_exams", "wrong", "chapter"}

FIGURE_PREFIX_RE = re.compile(
    r"(?:그림|Fig\.?|Figure)\s*\d+\s*[-‐‑‒–—―－]\s*\d+[A-Za-z]?\s*[.)]?\s*",
    re.IGNORECASE,
)
PANEL_PREFIX_RE = re.compile(r"^[A-Z](?:\s*,\s*[A-Z])*\s*[,.]\s*", re.IGNORECASE)
PANEL_RANGE_PREFIX_RE = re.compile(r"^[A-Z]\s*~\s*[A-Z]\s*,\s*", re.IGNORECASE)
INLINE_PANEL_RE = re.compile(r"^(.{2,24}?)\s+([A-Z])\s*,\s*(.+)$", re.IGNORECASE)
SUBJECT_TITLE_RE = re.compile(r"^(.{2,24}?)(?:에서|의)\s+")
DESCRIPTIVE_ENDINGS = (
    "관찰된다",
    "관찰되며",
    "보인다",
    "나타난다",
    "있다",
    "없다",
    "필요하다",
    "경우",
    "것이다",
    "소견",
)
CHAPTER_TITLES = {
    "16": "치아우식증의 영상진단",
    "17": "치주질환의 영상진단",
    "18": "발육성 치아 이상의 영상진단",
    "19": "후천성 치아 이상의 영상진단",
    "20": "구강악안면부 염증질환의 진단",
    "21": "구강악안면부 낭의 영상진단",
    "22": "구강악안면부 양성종양의 영상진단",
    "23": "구강악안면부 악성종양의 영상진단",
    "24": "구강악안면부에 나타나는 기타 골질환의 영상진단",
    "25": "측두하악관절의 영상진단",
    "26": "상악동의 영상진단",
    "27": "타액선의 영상진단",
    "28": "구강악안면부 외상의 진단",
    "29": "연조직 석회화의 영상진단",
    "30": "구강악안면부에 발현되는 전신질환의 영상진단",
    "31": "구강악안면부 발육장애의 영상진단",
    "32": "치과 임플란트를 위한 진단영상",
}


def normalize_limit(value: Any, default: Any = DEFAULT_SESSION_SIZE) -> int | None:
    if isinstance(value, str) and value.lower() == "all":
        return None
    try:
        limit = int(value)
    except (TypeError, ValueError):
        if isinstance(default, str) and default.lower() == "all":
            return None
        limit = default
    return min(MAX_SESSION_SIZE, max(1, limit))


def is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def image_url(file_path: str) -> str:
    return "/" + file_path.replace("\\", "/")


def attach_image_url(card: dict) -> dict:
    card["image_url"] = image_url(card["file_path"])
    return card


def normalized_caption_body(caption: str) -> str:
    match = FIGURE_PREFIX_RE.search(caption or "")
    body = (caption or "")[match.end() :] if match else caption or ""
    body = body.replace("·", "ㆍ")
    return " ".join(body.split())


def clean_title_prefix(value: str) -> str:
    text = PANEL_RANGE_PREFIX_RE.sub("", value.strip(), count=1)
    text = re.sub(r"^[A-Z]\s*~\s*[A-Z]\s*", "", text, count=1, flags=re.IGNORECASE).strip()
    return PANEL_PREFIX_RE.sub("", text, count=1).strip()


def is_title_candidate(value: str) -> bool:
    text = clean_title_prefix(value)
    if not text:
        return False
    if re.fullmatch(r"[A-Z]\s*~?", text, re.IGNORECASE):
        return False
    if re.match(r"^[A-Z]\b", text, re.IGNORECASE):
        return False
    if len(text) > 34:
        return False
    if any(text.endswith(ending) for ending in DESCRIPTIVE_ENDINGS):
        return False
    return True


def split_inline_panel_title(value: str) -> tuple[str, str] | None:
    if PANEL_RANGE_PREFIX_RE.match(value.strip()):
        return None
    match = INLINE_PANEL_RE.match(value.strip())
    if not match:
        return None
    title = clean_title_prefix(match.group(1))
    if not is_title_candidate(title):
        return None
    return title, f"{match.group(2).upper()}, {match.group(3).strip()}"


def split_answer_caption(caption: str) -> dict[str, str]:
    body = normalized_caption_body(caption)
    if not body:
        return {"answer_title": "", "answer_detail": ""}

    first, dot, rest = body.partition(".")
    first = first.strip()
    rest = rest.strip()

    inline_panel = split_inline_panel_title(first)
    if inline_panel:
        title, first_detail = inline_panel
        detail_parts = [part for part in [first_detail, rest] if part]
        return {"answer_title": title, "answer_detail": ". ".join(detail_parts)}

    patient_match = re.match(r"^(.{2,24}?)(?:\s+환자(?:의)?\b)(.*)$", first)
    if patient_match and is_title_candidate(patient_match.group(1)):
        title = patient_match.group(1).strip()
        remaining_first = f"환자{patient_match.group(2)}".strip()
        detail_parts = [part for part in [remaining_first, rest] if part]
        return {"answer_title": title, "answer_detail": ". ".join(detail_parts)}

    subject_match = SUBJECT_TITLE_RE.match(first)
    if subject_match and is_title_candidate(subject_match.group(1)):
        return {"answer_title": clean_title_prefix(subject_match.group(1)), "answer_detail": body}

    if dot and is_title_candidate(first):
        return {"answer_title": clean_title_prefix(first), "answer_detail": rest}
    if dot:
        second, _, second_rest = rest.partition(".")
        if is_title_candidate(second):
            return {"answer_title": clean_title_prefix(second), "answer_detail": second_rest.strip()}
    if not dot and is_title_candidate(first):
        return {"answer_title": clean_title_prefix(first), "answer_detail": ""}
    return {"answer_title": "", "answer_detail": body}


def infer_chapter(text: str) -> str:
    match = FIGURE_TAG_RE.search(text or "")
    return match.group("chapter") if match else "Unknown"


def chapter_title(chapter: str) -> str:
    return CHAPTER_TITLES.get(str(chapter), "")


def normalize_source(value: Any) -> str:
    source = str(value or "all")
    return source if source in VALID_SOURCES else "all"


def figure_sort_key(card: dict) -> tuple[int, int, int, int, int, int, int]:
    match = FIGURE_TAG_RE.search(card.get("caption_text", ""))
    source_page = int(card.get("source_page") or 0)
    image_index = int(card.get("page_image_index") or 0)
    card_id = int(card.get("card_id") or 0)
    if not match:
        return (1, source_page, 0, 0, 0, image_index, card_id)
    label = match.group("label") or ""
    panel_order = ord(label.upper()) - ord("A") + 1 if label else 0
    return (
        0,
        int(match.group("chapter")),
        int(match.group("figure")),
        panel_order,
        source_page,
        image_index,
        card_id,
    )


def enrich_card(row: sqlite3.Row) -> dict:
    card = row_to_dict(row)
    card["chapter"] = infer_chapter(card.get("caption_text", ""))
    card["chapter_title"] = chapter_title(card["chapter"])
    card["is_favorite"] = bool(card.get("is_favorite"))
    card["is_past_exam"] = bool(card.get("is_past_exam"))
    card.update(split_answer_caption(card.get("caption_text", "")))
    return attach_image_url(card)


def card_images(conn: sqlite3.Connection, card_ids: list[int]) -> dict[int, list[dict]]:
    if not card_ids:
        return {}
    placeholders = ",".join("?" for _ in card_ids)
    rows = conn.execute(
        f"""
        SELECT
            ci.card_id,
            ci.image_id,
            ci.sort_order,
            ci.source_caption_text,
            i.file_path,
            i.width AS image_width,
            i.height AS image_height,
            i.bbox_json AS image_bbox,
            i.page_image_index,
            i.is_duplicate
        FROM card_images ci
        JOIN extracted_images i ON i.id = ci.image_id
        WHERE ci.card_id IN ({placeholders})
        ORDER BY ci.card_id, ci.sort_order, ci.id
        """,
        card_ids,
    ).fetchall()
    grouped: dict[int, list[dict]] = {card_id: [] for card_id in card_ids}
    for row in rows:
        item = row_to_dict(row)
        item["image_url"] = image_url(item["file_path"])
        grouped.setdefault(int(row["card_id"]), []).append(item)
    return grouped


def attach_images(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    grouped = card_images(conn, [int(card["card_id"]) for card in cards])
    for card in cards:
        images = grouped.get(int(card["card_id"]), [])
        card["images"] = images
        card["image_count"] = len(images)
    return cards


def available_cards(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
    randomize: bool = False,
    source: str = "all",
    chapter: str | None = None,
) -> list[dict]:
    source = normalize_source(source)
    rows = conn.execute(
        """
        SELECT
            c.id AS card_id,
            c.document_id,
            c.source_page,
            c.caption_text,
            c.confidence,
            c.notes,
            i.id AS image_id,
            i.file_path,
            i.page_image_index,
            i.width AS image_width,
            i.height AS image_height,
            i.is_duplicate,
            lr.result AS last_review_result,
            CASE WHEN f.card_id IS NULL THEN 0 ELSE 1 END AS is_favorite,
            CASE WHEN pe.card_id IS NULL THEN 0 ELSE 1 END AS is_past_exam
        FROM cards c
        JOIN card_images ci ON ci.card_id = c.id
        JOIN extracted_images i ON i.id = ci.image_id
        LEFT JOIN study_favorites f ON f.card_id = c.id
        LEFT JOIN study_past_exams pe ON pe.card_id = c.id
        LEFT JOIN study_reviews lr ON lr.id = (
            SELECT sr.id
            FROM study_reviews sr
            WHERE sr.card_id = c.id
            ORDER BY datetime(sr.reviewed_at) DESC, sr.id DESC
            LIMIT 1
        )
        WHERE ci.sort_order = (
            SELECT MIN(sort_order) FROM card_images WHERE card_id = c.id
        )
        ORDER BY c.source_page, c.id
        """
    ).fetchall()
    cards = [enrich_card(row) for row in rows]
    attach_images(conn, cards)
    if source == "favorites":
        cards = [card for card in cards if card["is_favorite"]]
    elif source == "past_exams":
        cards = [card for card in cards if card["is_past_exam"]]
    elif source == "wrong":
        cards = [card for card in cards if card.get("last_review_result") == "wrong"]
    elif source == "chapter":
        chapter_value = str(chapter or "")
        cards = [card for card in cards if card["chapter"] == chapter_value]

    cards.sort(key=figure_sort_key)

    if randomize:
        random.shuffle(cards)

    start = max(0, offset)
    end = None if limit is None else start + limit
    return cards[start:end]


def create_session(
    conn: sqlite3.Connection,
    *,
    requested_count: Any = DEFAULT_SESSION_SIZE,
    source: Any = "all",
    chapter: Any = None,
    ordered: Any = True,
) -> dict:
    limit = normalize_limit(requested_count)
    source_value = normalize_source(source)
    chapter_value = str(chapter) if chapter is not None else None
    cards = available_cards(
        conn,
        limit=limit,
        randomize=not is_truthy(ordered),
        source=source_value,
        chapter=chapter_value,
    )
    source_filter = source_value if source_value != "chapter" else f"chapter:{chapter_value}"
    cursor = conn.execute(
        """
        INSERT INTO study_sessions (card_count, reviewed_count, status, source_filter)
        VALUES (?, 0, ?, ?)
        """,
        (len(cards), "completed" if not cards else "active", source_filter),
    )
    session_id = int(cursor.lastrowid)
    if not cards:
        conn.execute(
            "UPDATE study_sessions SET completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (session_id,),
        )
    conn.commit()
    return {
        "session_id": session_id,
        "card_count": len(cards),
        "source": source_value,
        "chapter": chapter_value,
        "cards": cards,
    }


def record_review(
    conn: sqlite3.Connection,
    *,
    session_id: Any,
    card_id: Any,
    result: str,
) -> dict:
    if result not in VALID_RESULTS:
        raise ValueError("Invalid result")
    session = conn.execute(
        "SELECT id, card_count FROM study_sessions WHERE id = ?",
        (int(session_id),),
    ).fetchone()
    if session is None:
        raise LookupError("Session not found")
    card = conn.execute("SELECT id FROM cards WHERE id = ?", (int(card_id),)).fetchone()
    if card is None:
        raise LookupError("Card not found")

    cursor = conn.execute(
        """
        INSERT INTO study_reviews (session_id, card_id, result)
        VALUES (?, ?, ?)
        """,
        (int(session_id), int(card_id), result),
    )
    reviewed_count = conn.execute(
        "SELECT COUNT(*) AS n FROM study_reviews WHERE session_id = ?",
        (int(session_id),),
    ).fetchone()["n"]
    completed = reviewed_count >= session["card_count"]
    conn.execute(
        """
        UPDATE study_sessions
        SET
            reviewed_count = ?,
            status = ?,
            completed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE completed_at END
        WHERE id = ?
        """,
        (reviewed_count, "completed" if completed else "active", 1 if completed else 0, int(session_id)),
    )
    conn.commit()
    return {
        "review_id": int(cursor.lastrowid),
        "session_id": int(session_id),
        "card_id": int(card_id),
        "result": result,
        "reviewed_count": reviewed_count,
        "completed": completed,
    }


def study_summary(conn: sqlite3.Connection) -> dict:
    available = conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"]
    reviewed_cards = conn.execute(
        "SELECT COUNT(DISTINCT card_id) AS n FROM study_reviews"
    ).fetchone()["n"]
    total_reviews = conn.execute("SELECT COUNT(*) AS n FROM study_reviews").fetchone()["n"]
    today_reviews = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM study_reviews
        WHERE date(reviewed_at, 'localtime') = date('now', 'localtime')
        """
    ).fetchone()["n"]
    favorite_cards = conn.execute("SELECT COUNT(*) AS n FROM study_favorites").fetchone()["n"]
    past_exam_cards = conn.execute("SELECT COUNT(*) AS n FROM study_past_exams").fetchone()["n"]
    by_result = {"correct": 0, "wrong": 0, "unsure": 0}
    for row in conn.execute("SELECT result, COUNT(*) AS count FROM study_reviews GROUP BY result"):
        by_result[row["result"]] = row["count"]

    return {
        "available_cards": available,
        "reviewed_cards": reviewed_cards,
        "total_reviews": total_reviews,
        "today_reviews": today_reviews,
        "favorite_cards": favorite_cards,
        "past_exam_cards": past_exam_cards,
        "correct": by_result["correct"],
        "wrong": by_result["wrong"],
        "unsure": by_result["unsure"],
    }


def study_sections(conn: sqlite3.Connection) -> dict:
    cards = available_cards(conn)
    chapters: dict[str, int] = {}
    for card in cards:
        chapters[card["chapter"]] = chapters.get(card["chapter"], 0) + 1
    chapter_rows = [
        {"chapter": chapter, "title": chapter_title(chapter), "count": count}
        for chapter, count in sorted(
            chapters.items(),
            key=lambda item: (9999 if item[0] == "Unknown" else int(item[0]), item[0]),
        )
    ]
    return {
        "all": len(cards),
        "favorites": sum(1 for card in cards if card["is_favorite"]),
        "past_exams": sum(1 for card in cards if card["is_past_exam"]),
        "wrong": sum(1 for card in cards if card.get("last_review_result") == "wrong"),
        "chapters": chapter_rows,
    }


def set_favorite(conn: sqlite3.Connection, *, card_id: Any, favorite: Any) -> dict:
    card = conn.execute("SELECT id FROM cards WHERE id = ?", (int(card_id),)).fetchone()
    if card is None:
        raise LookupError("Card not found")
    is_favorite = bool(favorite)
    if is_favorite:
        conn.execute("INSERT OR IGNORE INTO study_favorites (card_id) VALUES (?)", (int(card_id),))
    else:
        conn.execute("DELETE FROM study_favorites WHERE card_id = ?", (int(card_id),))
    conn.commit()
    return {"card_id": int(card_id), "is_favorite": is_favorite}


def set_past_exam(conn: sqlite3.Connection, *, card_id: Any, past_exam: Any) -> dict:
    card = conn.execute("SELECT id FROM cards WHERE id = ?", (int(card_id),)).fetchone()
    if card is None:
        raise LookupError("Card not found")
    is_past_exam = is_truthy(past_exam)
    if is_past_exam:
        conn.execute("INSERT OR IGNORE INTO study_past_exams (card_id) VALUES (?)", (int(card_id),))
    else:
        conn.execute("DELETE FROM study_past_exams WHERE card_id = ?", (int(card_id),))
    conn.commit()
    return {"card_id": int(card_id), "is_past_exam": is_past_exam}
