from __future__ import annotations

import json
import random
import sqlite3
from typing import Any

from .db import CARD_TYPES, row_to_dict
from .media import media_url


DEFAULT_SESSION_SIZE = "all"
MAX_SESSION_SIZE = 100
VALID_RESULTS = {"correct", "wrong"}
VALID_SOURCES = {"all", "favorites", "past_exams", "wrong", "chapter"}


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


def chapter_title(chapter: str) -> str:
    return "" if str(chapter or "Unknown") == "Unknown" else f"단원 {chapter}"


def normalize_source(value: Any) -> str:
    source = str(value or "all")
    return source if source in VALID_SOURCES else "all"


def normalize_card_type(value: Any) -> str:
    card_type = str(value or "")
    return card_type if card_type in CARD_TYPES else ""


def json_array(value: object) -> list:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def normalize_choices(value: object) -> list[dict[str, str]]:
    choices: list[dict[str, str]] = []
    for index, item in enumerate(json_array(value)):
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            choice_id = str(item.get("id") or index + 1)
        else:
            text = str(item or "").strip()
            choice_id = str(index + 1)
        if text:
            choices.append({"id": choice_id, "text": text})
    return choices


def normalize_choice_ids(value: object) -> list[str]:
    return [str(item) for item in json_array(value) if str(item).strip()]


def card_media(
    conn: sqlite3.Connection,
    card_ids: list[int],
    *,
    include_file_path: bool = False,
) -> dict[int, list[dict]]:
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
            i.width AS width,
            i.height AS height,
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
        file_path = item["file_path"]
        media = {
            "kind": "image",
            "src": media_url(file_path),
            "alt": item.get("source_caption_text") or "카드 이미지",
            "width": item.get("width"),
            "height": item.get("height"),
            "image_id": item.get("image_id"),
            "sort_order": item.get("sort_order"),
            "image_bbox": item.get("image_bbox"),
            "page_image_index": item.get("page_image_index"),
            "is_duplicate": bool(item.get("is_duplicate")),
        }
        if include_file_path:
            media["file_path"] = file_path
        grouped.setdefault(int(row["card_id"]), []).append(media)
    return grouped


def card_dto(row: sqlite3.Row, media: list[dict]) -> dict:
    item = row_to_dict(row)
    card_id = int(item["card_id"])
    card_type = str(item.get("card_type") or "image")
    if card_type not in CARD_TYPES:
        card_type = "image"

    favorite = bool(item.get("is_favorite"))
    past_exam = bool(item.get("is_past_exam"))
    last_result = item.get("last_review_result") or ""
    chapter = str(item.get("chapter") or "Unknown")
    answer_text = str(item.get("answer_text") or "")
    answer_explanation = str(item.get("answer_explanation") or "")

    dto = {
        "id": str(card_id),
        "card_id": card_id,
        "type": card_type,
        "prompt": {"text": str(item.get("prompt_text") or "")},
        "media": media,
        "choices": normalize_choices(item.get("choices_json")),
        "answer": {
            "text": answer_text,
            "choiceIds": normalize_choice_ids(item.get("answer_choice_ids_json")),
            "explanation": answer_explanation,
        },
        "meta": {
            "chapter": chapter,
            "chapterTitle": chapter_title(chapter),
            "sourcePage": item.get("source_page"),
            "sourceLabel": item.get("source_label") or "",
            "tags": [],
        },
        "review": {
            "favorite": favorite,
            "pastExam": past_exam,
            "lastResult": last_result,
        },
        "source": {
            "documentId": item.get("document_id"),
            "captionText": item.get("caption_text") or "",
            "confidence": item.get("confidence"),
            "notes": item.get("notes") or "",
        },
        "sortOrder": int(item.get("sort_order") or 0),
    }

    # Transitional conveniences for admin tools and tests. The study UI uses the
    # structured fields above.
    dto["is_favorite"] = favorite
    dto["is_past_exam"] = past_exam
    dto["last_review_result"] = last_result
    dto["chapter"] = chapter
    dto["chapter_title"] = dto["meta"]["chapterTitle"]
    dto["source_page"] = item.get("source_page")
    dto["source_label"] = item.get("source_label") or ""
    dto["image_count"] = len(media)
    return dto


def load_card_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            c.id AS card_id,
            c.document_id,
            c.source_page,
            c.caption_text,
            c.card_type,
            c.prompt_text,
            c.answer_text,
            c.answer_explanation,
            c.choices_json,
            c.answer_choice_ids_json,
            c.chapter,
            c.source_label,
            c.sort_order,
            c.confidence,
            c.notes,
            lr.result AS last_review_result,
            CASE WHEN f.card_id IS NULL THEN 0 ELSE 1 END AS is_favorite,
            CASE WHEN pe.card_id IS NULL THEN 0 ELSE 1 END AS is_past_exam
        FROM cards c
        LEFT JOIN study_favorites f ON f.card_id = c.id
        LEFT JOIN study_past_exams pe ON pe.card_id = c.id
        LEFT JOIN study_reviews lr ON lr.id = (
            SELECT sr.id
            FROM study_reviews sr
            WHERE sr.card_id = c.id
            ORDER BY datetime(sr.reviewed_at) DESC, sr.id DESC
            LIMIT 1
        )
        ORDER BY c.sort_order, c.source_page, c.id
        """
    ).fetchall()


def card_matches_query(card: dict, query: str) -> bool:
    needle = str(query or "").strip().lower()
    if not needle:
        return True
    fields = [
        card["prompt"]["text"],
        card["answer"]["text"],
        card["answer"]["explanation"],
        card["meta"]["sourceLabel"],
        card["source"]["captionText"],
        card["source"]["notes"],
    ]
    return any(needle in str(value or "").lower() for value in fields)


def available_cards(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
    randomize: bool = False,
    source: str = "all",
    chapter: str | None = None,
    card_type: str | None = None,
    q: str | None = None,
    include_file_path: bool = False,
) -> list[dict]:
    source = normalize_source(source)
    chapter_value = str(chapter) if chapter not in (None, "") else ""
    card_type_value = normalize_card_type(card_type)
    rows = load_card_rows(conn)
    media_by_card = card_media(
        conn,
        [int(row["card_id"]) for row in rows],
        include_file_path=include_file_path,
    )
    cards = [card_dto(row, media_by_card.get(int(row["card_id"]), [])) for row in rows]

    if source == "favorites":
        cards = [card for card in cards if card["review"]["favorite"]]
    elif source == "past_exams":
        cards = [card for card in cards if card["review"]["pastExam"]]
    elif source == "wrong":
        cards = [card for card in cards if card["review"]["lastResult"] == "wrong"]
    elif source == "chapter":
        cards = [card for card in cards if card["meta"]["chapter"] == chapter_value]

    if source != "chapter" and chapter_value:
        cards = [card for card in cards if card["meta"]["chapter"] == chapter_value]
    if card_type_value:
        cards = [card for card in cards if card["type"] == card_type_value]
    if q and str(q).strip():
        cards = [card for card in cards if card_matches_query(card, str(q))]

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
    card_type: Any = None,
    q: Any = None,
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
        card_type=card_type,
        q=q,
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
        raise ValueError("지원하지 않는 평가 결과입니다")
    session = conn.execute(
        "SELECT id, card_count FROM study_sessions WHERE id = ?",
        (int(session_id),),
    ).fetchone()
    if session is None:
        raise LookupError("세션을 찾을 수 없습니다")
    card = conn.execute("SELECT id FROM cards WHERE id = ?", (int(card_id),)).fetchone()
    if card is None:
        raise LookupError("카드를 찾을 수 없습니다")

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
        "id": str(card_id),
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
    by_result = {"correct": 0, "wrong": 0}
    for row in conn.execute("SELECT result, COUNT(*) AS count FROM study_reviews GROUP BY result"):
        if row["result"] in by_result:
            by_result[row["result"]] = row["count"]

    return {
        "available_cards": available,
        "past_exam_cards": past_exam_cards,
        "reviewed_cards": reviewed_cards,
        "total_reviews": total_reviews,
        "today_reviews": today_reviews,
        "favorite_cards": favorite_cards,
        "correct": by_result["correct"],
        "wrong": by_result["wrong"],
    }


def sorted_chapter_rows(cards: list[dict]) -> list[dict]:
    chapters: dict[str, dict] = {}
    for card in cards:
        chapter = card["meta"]["chapter"] or "Unknown"
        item = chapters.setdefault(
            chapter,
            {"chapter": chapter, "title": card["meta"].get("chapterTitle") or "", "count": 0},
        )
        item["count"] += 1

    def chapter_key(item: dict) -> tuple[int, str]:
        chapter = str(item["chapter"])
        try:
            numeric = int(chapter)
        except ValueError:
            numeric = 9999
        return numeric, chapter

    return sorted(chapters.values(), key=chapter_key)


def study_sections(conn: sqlite3.Connection) -> dict:
    cards = available_cards(conn)
    return {
        "all": len(cards),
        "favorites": sum(1 for card in cards if card["review"]["favorite"]),
        "past_exams": sum(1 for card in cards if card["review"]["pastExam"]),
        "wrong": sum(1 for card in cards if card["review"]["lastResult"] == "wrong"),
        "chapters": sorted_chapter_rows(cards),
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
    return {
        "card_id": int(card_id),
        "id": str(card_id),
        "is_favorite": is_favorite,
        "review": {"favorite": is_favorite},
    }


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
    return {
        "card_id": int(card_id),
        "id": str(card_id),
        "is_past_exam": is_past_exam,
        "review": {"pastExam": is_past_exam},
    }
