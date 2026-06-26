from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .answer_fields import answer_fields_from_caption
from .db import CARD_TYPES, DEFAULT_DB_PATH, append_note, connect, init_db
from .export_pages import DEFAULT_OUTPUT_DIR, export_pages
from .media import safe_media_path
from .study import (
    available_cards,
    card_dto,
    card_media,
    create_session,
    record_review,
    set_favorite,
    set_past_exam,
    study_sections,
    study_summary,
)


STATIC_DIR = Path(__file__).parent / "static"


def int_query(query: dict[str, list[str]], key: str, default: int, *, minimum: int = 0, maximum: int = 500) -> int:
    try:
        value = int((query.get(key) or [str(default)])[0])
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def figure_key(source_label: str) -> str:
    label = str(source_label or "").strip()
    if label.lower().startswith("fig."):
        label = label[4:].strip()
    return label.rstrip(".")


class ReviewServer(BaseHTTPRequestHandler):
    server_version = "FlashcardReview/0.3"

    @property
    def db_path(self) -> Path:
        return self.server.db_path  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def send_json(self, payload: dict | list, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def with_db(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        init_db(conn)
        return conn

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.serve_static("index.html")
        if parsed.path == "/review":
            return self.serve_static("review.html")
        if parsed.path.startswith("/static/"):
            return self.serve_static(parsed.path.removeprefix("/static/"))
        if parsed.path.startswith("/media/"):
            return self.serve_media(parsed.path.removeprefix("/media/"))
        if parsed.path == "/api/study/summary":
            return self.api_study_summary()
        if parsed.path == "/api/study/sections":
            return self.api_study_sections()
        if parsed.path == "/api/study/cards":
            return self.api_study_cards(parse_qs(parsed.query))
        if parsed.path == "/api/cards":
            return self.api_cards(parse_qs(parsed.query))
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/api/study/session":
            return self.api_create_study_session(self.read_json_body())
        if parsed.path == "/api/study/review":
            return self.api_record_study_review(self.read_json_body())
        if parsed.path == "/api/study/favorite":
            return self.api_set_study_favorite(self.read_json_body())
        if parsed.path == "/api/study/past-exam":
            return self.api_set_study_past_exam(self.read_json_body())
        if parsed.path == "/api/cards/merge":
            return self.api_merge_cards(self.read_json_body())
        if parsed.path == "/api/static-export":
            return self.api_static_export()
        if len(parts) == 4 and parts[:2] == ["api", "cards"] and parts[3] == "split":
            return self.api_split_card(int(parts[2]))
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "cards"]:
            return self.api_update_card(int(parts[2]), self.read_json_body())
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "cards"]:
            return self.api_delete_card(int(parts[2]))
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def serve_static(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error_json(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not path.exists() or not path.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Static file not found")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_media(self, relative_path: str) -> None:
        path = safe_media_path(relative_path)
        if path is None:
            self.send_error_json(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not path.exists() or not path.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Media file not found")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def api_study_summary(self) -> None:
        conn = self.with_db()
        try:
            payload = study_summary(conn)
        finally:
            conn.close()
        self.send_json(payload)

    def api_study_sections(self) -> None:
        conn = self.with_db()
        try:
            payload = study_sections(conn)
        finally:
            conn.close()
        self.send_json(payload)

    def api_study_cards(self, query: dict[str, list[str]]) -> None:
        limit_value = (query.get("limit") or ["25"])[0]
        limit = None if str(limit_value).lower() == "all" else min(100, max(1, int(limit_value)))
        offset = max(0, int((query.get("offset") or ["0"])[0]))
        source = (query.get("source") or ["all"])[0]
        chapter = (query.get("chapter") or [None])[0]
        card_type = (query.get("card_type") or [None])[0]
        search = (query.get("q") or [None])[0]
        conn = self.with_db()
        try:
            cards = available_cards(
                conn,
                limit=limit,
                offset=offset,
                source=source,
                chapter=chapter,
                card_type=card_type,
                q=search,
            )
        finally:
            conn.close()
        self.send_json({"items": cards, "limit": limit, "offset": offset})

    def api_create_study_session(self, payload: dict) -> None:
        conn = self.with_db()
        try:
            session = create_session(
                conn,
                requested_count=payload.get("count", "all"),
                source=payload.get("source", "all"),
                chapter=payload.get("chapter"),
                card_type=payload.get("card_type"),
                q=payload.get("q"),
                ordered=payload.get("ordered", False),
            )
        finally:
            conn.close()
        self.send_json(session, HTTPStatus.CREATED)

    def api_record_study_review(self, payload: dict) -> None:
        conn = self.with_db()
        try:
            try:
                result = record_review(
                    conn,
                    session_id=payload.get("session_id"),
                    card_id=payload.get("card_id"),
                    result=str(payload.get("result", "")),
                )
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return
        finally:
            conn.close()
        self.send_json(result, HTTPStatus.CREATED)

    def api_set_study_favorite(self, payload: dict) -> None:
        conn = self.with_db()
        try:
            try:
                result = set_favorite(
                    conn,
                    card_id=payload.get("card_id"),
                    favorite=payload.get("favorite"),
                )
            except (TypeError, ValueError):
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid card_id")
                return
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return
        finally:
            conn.close()
        self.send_json(result)

    def api_set_study_past_exam(self, payload: dict) -> None:
        conn = self.with_db()
        try:
            try:
                result = set_past_exam(
                    conn,
                    card_id=payload.get("card_id"),
                    past_exam=payload.get("past_exam"),
                )
            except (TypeError, ValueError):
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid card_id")
                return
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return
        finally:
            conn.close()
        self.send_json(result)

    def api_static_export(self) -> None:
        try:
            payload = export_pages(self.server.db_path, DEFAULT_OUTPUT_DIR, clean=True)  # type: ignore[attr-defined]
        except Exception as error:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
            return
        self.send_json(payload)

    def api_cards(self, query: dict[str, list[str]]) -> None:
        conn = self.with_db()
        try:
            payload = list_cards(conn, query)
        finally:
            conn.close()
        self.send_json(payload)

    def api_update_card(self, card_id: int, payload: dict) -> None:
        conn = self.with_db()
        try:
            try:
                card = update_card(
                    conn,
                    card_id,
                    caption_text=payload.get("caption_text") if "caption_text" in payload else None,
                    notes=payload.get("notes") if "notes" in payload else None,
                    card_type=payload.get("card_type") if "card_type" in payload else None,
                    prompt_text=payload.get("prompt_text") if "prompt_text" in payload else None,
                    answer_text=payload.get("answer_text") if "answer_text" in payload else None,
                    answer_explanation=payload.get("answer_explanation")
                    if "answer_explanation" in payload
                    else None,
                    choices=payload.get("choices") if "choices" in payload else None,
                    answer_choice_ids=payload.get("answer_choice_ids")
                    if "answer_choice_ids" in payload
                    else None,
                    chapter=payload.get("chapter") if "chapter" in payload else None,
                    source_label=payload.get("source_label") if "source_label" in payload else None,
                    sort_order=payload.get("sort_order") if "sort_order" in payload else None,
                )
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
            except LookupError:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Card not found")
                return
        finally:
            conn.close()
        self.send_json(card)

    def api_delete_card(self, card_id: int) -> None:
        conn = self.with_db()
        try:
            row = conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
            if row is None:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Card not found")
                return
            conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
            conn.commit()
        finally:
            conn.close()
        self.send_json({"ok": True, "card_id": card_id})

    def api_merge_cards(self, payload: dict) -> None:
        card_ids = unique_ints(payload.get("card_ids") or [])
        if len(card_ids) < 2:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Select at least two cards")
            return
        keep_id = int(payload.get("keep_card_id") or card_ids[0])
        if keep_id not in card_ids:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "keep_card_id must be selected")
            return

        conn = self.with_db()
        try:
            cards = conn.execute(
                f"SELECT * FROM cards WHERE id IN ({','.join('?' for _ in card_ids)})",
                card_ids,
            ).fetchall()
            if len(cards) != len(card_ids):
                self.send_error_json(HTTPStatus.NOT_FOUND, "One or more cards were not found")
                return
            merge_cards(conn, card_ids, keep_id, payload.get("caption_text"))
            conn.commit()
            card = get_card_payload(conn, keep_id)
        finally:
            conn.close()
        self.send_json(card)

    def api_split_card(self, card_id: int) -> None:
        conn = self.with_db()
        try:
            images = conn.execute(
                """
                SELECT ci.*, i.page_number
                FROM card_images ci
                JOIN extracted_images i ON i.id = ci.image_id
                WHERE ci.card_id = ?
                ORDER BY ci.sort_order, ci.id
                """,
                (card_id,),
            ).fetchall()
            if len(images) <= 1:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Card has only one image")
                return
            new_ids = split_card(conn, card_id, images)
            conn.commit()
        finally:
            conn.close()
        self.send_json({"ok": True, "card_ids": new_ids})


def unique_ints(values: list | tuple) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in {"", None}:
            continue
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def json_array(value: object, field_name: str) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value) if value.strip() else []
        except json.JSONDecodeError as error:
            raise ValueError(f"{field_name} must be a JSON array") from error
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise ValueError(f"{field_name} must be an array")
    return json.dumps(parsed, ensure_ascii=False)


def get_card_payload(conn: sqlite3.Connection, card_id: int) -> dict:
    payload = list_cards(conn, {"id": [str(card_id)], "limit": ["1"]})
    if not payload["items"]:
        raise LookupError("Card not found")
    return payload["items"][0]


def update_card(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    caption_text: object = None,
    notes: object = None,
    card_type: object = None,
    prompt_text: object = None,
    answer_text: object = None,
    answer_explanation: object = None,
    choices: object = None,
    answer_choice_ids: object = None,
    chapter: object = None,
    source_label: object = None,
    sort_order: object = None,
) -> dict:
    updates: list[tuple[str, object]] = []
    if caption_text is not None:
        updates.append(("caption_text", str(caption_text)))
    if notes is not None:
        updates.append(("notes", str(notes)))
    if card_type is not None:
        next_type = str(card_type)
        if next_type not in CARD_TYPES:
            raise ValueError("Invalid card_type")
        updates.append(("card_type", next_type))
    if prompt_text is not None:
        updates.append(("prompt_text", str(prompt_text)))
    if answer_text is not None:
        updates.append(("answer_text", str(answer_text)))
    if answer_explanation is not None:
        updates.append(("answer_explanation", str(answer_explanation)))
    if choices is not None:
        updates.append(("choices_json", json_array(choices, "choices")))
    if answer_choice_ids is not None:
        updates.append(("answer_choice_ids_json", json_array(answer_choice_ids, "answer_choice_ids")))
    if chapter is not None:
        updates.append(("chapter", str(chapter or "Unknown")))
    if source_label is not None:
        updates.append(("source_label", str(source_label)))
    if sort_order is not None:
        try:
            updates.append(("sort_order", int(sort_order)))
        except (TypeError, ValueError) as error:
            raise ValueError("sort_order must be an integer") from error

    if not updates:
        raise ValueError("Nothing to update")
    row = conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise LookupError("Card not found")

    set_sql = ", ".join(f"{column} = ?" for column, _ in updates)
    values = [value for _, value in updates]
    conn.execute(
        f"UPDATE cards SET {set_sql}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [*values, card_id],
    )
    conn.commit()
    return get_card_payload(conn, card_id)


def list_cards(conn: sqlite3.Connection, query: dict[str, list[str]]) -> dict:
    limit = int_query(query, "limit", 25, minimum=1, maximum=200)
    offset = int_query(query, "offset", 0)
    params: list[object] = []
    where = ["1 = 1"]

    if query.get("id"):
        where.append("c.id = ?")
        params.append(int(query["id"][0]))
    if query.get("q") and query["q"][0].strip():
        where.append(
            """
            (
                c.prompt_text LIKE ?
                OR c.answer_text LIKE ?
                OR c.answer_explanation LIKE ?
                OR c.source_label LIKE ?
                OR c.notes LIKE ?
            )
            """
        )
        needle = f"%{query['q'][0].strip()}%"
        params.extend([needle, needle, needle, needle, needle])
    if query.get("chapter") and query["chapter"][0]:
        where.append("c.chapter = ?")
        params.append(str(query["chapter"][0]))
    if query.get("page") and query["page"][0]:
        where.append("c.source_page = ?")
        params.append(int(query["page"][0]))
    if query.get("figure") and query["figure"][0]:
        figure = query["figure"][0].strip()
        where.append("c.source_label LIKE ?")
        params.append(f"%{figure}%")
    if query.get("past_exam") and query["past_exam"][0] in {"1", "true", "yes"}:
        where.append("pe.card_id IS NOT NULL")
    if query.get("multi") and query["multi"][0] in {"1", "true", "yes"}:
        where.append("image_counts.image_count > 1")

    where_sql = " AND ".join(where)
    count = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM cards c
        LEFT JOIN study_past_exams pe ON pe.card_id = c.id
        LEFT JOIN (
            SELECT card_id, COUNT(*) AS image_count
            FROM card_images
            GROUP BY card_id
        ) image_counts ON image_counts.card_id = c.id
        WHERE {where_sql}
        """,
        params,
    ).fetchone()["n"]
    rows = conn.execute(
        f"""
        SELECT
            c.id AS card_id,
            c.document_id,
            c.caption_block_id,
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
            c.created_at,
            c.updated_at,
            image_counts.image_count,
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
        LEFT JOIN (
            SELECT card_id, COUNT(*) AS image_count
            FROM card_images
            GROUP BY card_id
        ) image_counts ON image_counts.card_id = c.id
        WHERE {where_sql}
        ORDER BY c.sort_order, c.source_page, c.id
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    items = [card_payload(conn, row) for row in rows]
    return {"items": items, "total": count, "limit": limit, "offset": offset}


def card_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    row_item = {key: row[key] for key in row.keys()}
    media = card_media(conn, [int(row_item["card_id"])]).get(int(row_item["card_id"]), [])
    item = card_dto(row, media)
    images = []
    for media_item in media:
        image_item = dict(media_item)
        image_item["image_url"] = image_item["src"]
        image_item["image_width"] = image_item["width"]
        image_item["image_height"] = image_item["height"]
        images.append(image_item)
    item["images"] = images
    item["image_url"] = images[0]["image_url"] if images else ""
    item["image_width"] = images[0]["image_width"] if images else None
    item["image_height"] = images[0]["image_height"] if images else None
    item["caption_text"] = item["source"]["captionText"]
    item["notes"] = item["source"]["notes"]
    item["confidence"] = item["source"]["confidence"]
    item["card_type"] = item["type"]
    item["prompt_text"] = item["prompt"]["text"]
    item["answer_text"] = item["answer"]["text"]
    item["answer_explanation"] = item["answer"]["explanation"]
    item["choices_json"] = row_item["choices_json"]
    item["answer_choice_ids_json"] = row_item["answer_choice_ids_json"]
    item["figure_key"] = figure_key(item["source_label"])
    item["created_at"] = row_item.get("created_at")
    item["updated_at"] = row_item.get("updated_at")
    return item


def merge_cards(
    conn: sqlite3.Connection,
    card_ids: list[int],
    keep_id: int,
    caption_text: object = None,
) -> None:
    ordered_ids = sorted(card_ids)
    cards = {
        int(row["id"]): row
        for row in conn.execute(
            f"SELECT * FROM cards WHERE id IN ({','.join('?' for _ in ordered_ids)}) ORDER BY source_page, id",
            ordered_ids,
        )
    }
    keep = cards[keep_id]
    images: list[tuple[int, str]] = []
    seen_images: set[int] = set()
    for card_id in ordered_ids:
        for row in conn.execute(
            """
            SELECT image_id, source_caption_text
            FROM card_images
            WHERE card_id = ?
            ORDER BY sort_order, id
            """,
            (card_id,),
        ):
            image_id = int(row["image_id"])
            if image_id in seen_images:
                continue
            seen_images.add(image_id)
            images.append((image_id, row["source_caption_text"] or cards[card_id]["caption_text"]))

    favorite = conn.execute(
        f"SELECT 1 FROM study_favorites WHERE card_id IN ({','.join('?' for _ in ordered_ids)}) LIMIT 1",
        ordered_ids,
    ).fetchone()
    past_exam = conn.execute(
        f"SELECT 1 FROM study_past_exams WHERE card_id IN ({','.join('?' for _ in ordered_ids)}) LIMIT 1",
        ordered_ids,
    ).fetchone()
    next_caption = str(caption_text).strip() if caption_text else keep["caption_text"]
    conn.execute(
        """
        UPDATE cards
        SET caption_text = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            next_caption,
            append_note(keep["notes"], f"merged_card_ids={','.join(map(str, ordered_ids))}"),
            keep_id,
        ),
    )
    conn.execute("DELETE FROM card_images WHERE card_id = ?", (keep_id,))
    for sort_order, (image_id, source_caption) in enumerate(images):
        conn.execute(
            """
            INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
            VALUES (?, ?, ?, ?)
            """,
            (keep_id, image_id, sort_order, source_caption),
        )
    delete_ids = [card_id for card_id in ordered_ids if card_id != keep_id]
    if delete_ids:
        conn.execute(
            f"DELETE FROM cards WHERE id IN ({','.join('?' for _ in delete_ids)})",
            delete_ids,
        )
    if favorite:
        conn.execute("INSERT OR IGNORE INTO study_favorites (card_id) VALUES (?)", (keep_id,))
    if past_exam:
        conn.execute("INSERT OR IGNORE INTO study_past_exams (card_id) VALUES (?)", (keep_id,))


def split_card(conn: sqlite3.Connection, card_id: int, images: list[sqlite3.Row]) -> list[int]:
    card = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if card is None:
        raise LookupError("Card not found")
    is_favorite = conn.execute("SELECT 1 FROM study_favorites WHERE card_id = ?", (card_id,)).fetchone()
    is_past_exam = conn.execute("SELECT 1 FROM study_past_exams WHERE card_id = ?", (card_id,)).fetchone()
    new_ids = [card_id]

    first = images[0]
    first_caption = first["source_caption_text"] or card["caption_text"]
    first_answer = answer_fields_from_caption(first_caption)
    conn.execute("DELETE FROM card_images WHERE card_id = ?", (card_id,))
    conn.execute(
        """
        UPDATE cards
        SET caption_text = ?, answer_text = ?, answer_explanation = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (first_caption, first_answer.answer_text, first_answer.answer_explanation, card_id),
    )
    conn.execute(
        """
        INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
        VALUES (?, ?, 0, ?)
        """,
        (card_id, first["image_id"], first_caption),
    )
    for offset, image in enumerate(images[1:], start=1):
        caption = image["source_caption_text"] or card["caption_text"]
        answer = answer_fields_from_caption(caption)
        cursor = conn.execute(
            """
            INSERT INTO cards
                (
                    document_id, caption_block_id, source_page, caption_text,
                    card_type, prompt_text, answer_text, answer_explanation,
                    choices_json, answer_choice_ids_json, chapter, source_label,
                    sort_order, confidence, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card["document_id"],
                card["caption_block_id"],
                image["page_number"],
                caption,
                card["card_type"],
                card["prompt_text"],
                answer.answer_text,
                answer.answer_explanation,
                card["choices_json"],
                card["answer_choice_ids_json"],
                card["chapter"],
                card["source_label"],
                int(card["sort_order"] or 0) + offset,
                card["confidence"],
                append_note(card["notes"], f"split_from_card_id={card_id}"),
            ),
        )
        new_id = int(cursor.lastrowid)
        new_ids.append(new_id)
        conn.execute(
            """
            INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
            VALUES (?, ?, 0, ?)
            """,
            (new_id, image["image_id"], caption),
        )
        if is_favorite:
            conn.execute("INSERT OR IGNORE INTO study_favorites (card_id) VALUES (?)", (new_id,))
        if is_past_exam:
            conn.execute("INSERT OR IGNORE INTO study_past_exams (card_id) VALUES (?)", (new_id,))
    return new_ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local flashcard UI.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    conn = connect(args.db)
    init_db(conn)
    conn.close()

    server = ThreadingHTTPServer((args.host, args.port), ReviewServer)
    server.db_path = args.db  # type: ignore[attr-defined]
    print(f"Flashcard UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
