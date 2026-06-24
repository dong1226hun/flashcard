from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sqlite3
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .caption_labels import FIGURE_TAG_RE
from .db import DEFAULT_DB_PATH, append_note, connect, init_db, row_to_dict
from .study import (
    available_cards,
    create_session,
    FIGURE_PREFIX_RE,
    record_review,
    set_favorite,
    set_past_exam,
    split_answer_caption,
    study_sections,
    study_summary,
)


STATIC_DIR = Path(__file__).parent / "static"
WORKSPACE_ROOT = Path.cwd().resolve()


def safe_asset_path(relative_path: str) -> Path | None:
    candidate = (WORKSPACE_ROOT / unquote(relative_path)).resolve()
    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError:
        return None
    return candidate


def image_url(file_path: str) -> str:
    return "/" + file_path.replace("\\", "/")


def int_query(query: dict[str, list[str]], key: str, default: int, *, minimum: int = 0, maximum: int = 500) -> int:
    try:
        value = int((query.get(key) or [str(default)])[0])
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def figure_key(caption: str) -> str:
    match = FIGURE_TAG_RE.search(caption or "")
    if not match:
        return ""
    return f"{match.group('chapter')}-{match.group('figure')}"


class ReviewServer(BaseHTTPRequestHandler):
    server_version = "FlashcardReview/0.2"

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
        if parsed.path.startswith("/assets/"):
            return self.serve_asset(parsed.path.removeprefix("/"))
        if parsed.path == "/api/study/summary":
            return self.api_study_summary()
        if parsed.path == "/api/study/sections":
            return self.api_study_sections()
        if parsed.path == "/api/study/cards":
            return self.api_study_cards(parse_qs(parsed.query))
        if parsed.path == "/api/cards":
            return self.api_cards(parse_qs(parsed.query))
        if parsed.path == "/api/cards/pdf-crop":
            return self.api_cards_pdf_crop(parse_qs(parsed.query))
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

    def serve_asset(self, relative_path: str) -> None:
        path = safe_asset_path(relative_path)
        if path is None:
            self.send_error_json(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not path.exists() or not path.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Asset not found")
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
        conn = self.with_db()
        try:
            cards = available_cards(conn, limit=limit, offset=offset, source=source, chapter=chapter)
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
                    caption_text=payload.get("caption_text"),
                    notes=payload.get("notes"),
                    answer_title=payload.get("answer_title") if "answer_title" in payload else None,
                    answer_detail=payload.get("answer_detail") if "answer_detail" in payload else None,
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

    def api_cards_pdf_crop(self, query: dict[str, list[str]]) -> None:
        raw_ids = ",".join(query.get("card_ids") or query.get("ids") or [])
        card_ids = unique_ints(raw_ids.replace(" ", "").split(","))
        if not card_ids:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "card_ids is required")
            return
        conn = self.with_db()
        try:
            try:
                payload = render_pdf_crop(conn, card_ids)
            except (LookupError, ValueError) as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return
        finally:
            conn.close()
        self.send_json(payload)


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


def get_card_payload(conn: sqlite3.Connection, card_id: int) -> dict:
    payload = list_cards(conn, {"id": [str(card_id)], "limit": ["1"]})
    if not payload["items"]:
        raise LookupError("Card not found")
    return payload["items"][0]


def compose_answer_caption(base_caption: str, answer_title: object = "", answer_detail: object = "") -> str:
    title = " ".join(str(answer_title or "").split())
    detail = " ".join(str(answer_detail or "").split())
    body = detail
    if title and detail:
        separator = "" if title.endswith((".", "?", "!")) else "."
        body = f"{title}{separator} {detail}"
    elif title:
        body = title

    match = FIGURE_PREFIX_RE.search(base_caption or "")
    prefix = (base_caption or "")[: match.end()] if match else ""
    if not prefix:
        return body
    return f"{prefix.rstrip()} {body}".strip()


def update_card(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    caption_text: object = None,
    notes: object = None,
    answer_title: object = None,
    answer_detail: object = None,
) -> dict:
    if caption_text is None and notes is None and answer_title is None and answer_detail is None:
        raise ValueError("Nothing to update")
    row = conn.execute("SELECT id, caption_text FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise LookupError("Card not found")

    next_caption = str(caption_text) if caption_text is not None else None
    if answer_title is not None or answer_detail is not None:
        base_caption = next_caption if next_caption is not None else row["caption_text"]
        current_answer = split_answer_caption(base_caption)
        title = current_answer["answer_title"] if answer_title is None else answer_title
        detail = current_answer["answer_detail"] if answer_detail is None else answer_detail
        next_caption = compose_answer_caption(base_caption, title, detail)

    if next_caption is not None:
        conn.execute(
            "UPDATE cards SET caption_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (next_caption, card_id),
        )
    if notes is not None:
        conn.execute(
            "UPDATE cards SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (str(notes), card_id),
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
        where.append("(c.caption_text LIKE ? OR c.notes LIKE ?)")
        needle = f"%{query['q'][0].strip()}%"
        params.extend([needle, needle])
    if query.get("chapter") and query["chapter"][0]:
        where.append("c.caption_text LIKE ?")
        params.append(f"%그림 {query['chapter'][0]}-%")
    if query.get("page") and query["page"][0]:
        where.append("c.source_page = ?")
        params.append(int(query["page"][0]))
    if query.get("figure") and query["figure"][0]:
        figure = query["figure"][0].strip()
        where.append("(c.caption_text LIKE ? OR c.caption_text LIKE ?)")
        params.extend([f"%그림 {figure}%", f"%Figure {figure}%"])
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
            c.confidence,
            c.notes,
            c.created_at,
            c.updated_at,
            i.id AS image_id,
            i.file_path,
            i.page_image_index,
            i.width AS image_width,
            i.height AS image_height,
            image_counts.image_count,
            CASE WHEN f.card_id IS NULL THEN 0 ELSE 1 END AS is_favorite,
            CASE WHEN pe.card_id IS NULL THEN 0 ELSE 1 END AS is_past_exam
        FROM cards c
        JOIN card_images ci ON ci.card_id = c.id
        JOIN extracted_images i ON i.id = ci.image_id
        LEFT JOIN study_favorites f ON f.card_id = c.id
        LEFT JOIN study_past_exams pe ON pe.card_id = c.id
        LEFT JOIN (
            SELECT card_id, COUNT(*) AS image_count
            FROM card_images
            GROUP BY card_id
        ) image_counts ON image_counts.card_id = c.id
        WHERE {where_sql}
          AND ci.sort_order = (
              SELECT MIN(sort_order) FROM card_images WHERE card_id = c.id
          )
        ORDER BY c.source_page, c.id
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    items = [card_payload(conn, row) for row in rows]
    return {"items": items, "total": count, "limit": limit, "offset": offset}


def card_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    item = row_to_dict(row)
    item["image_url"] = image_url(item["file_path"])
    item["is_favorite"] = bool(item["is_favorite"])
    item["is_past_exam"] = bool(item["is_past_exam"])
    item["figure_key"] = figure_key(item["caption_text"])
    item.update(split_answer_caption(item["caption_text"]))
    images = []
    for image in conn.execute(
        """
        SELECT
            ci.image_id,
            ci.sort_order,
            ci.source_caption_text,
            i.file_path,
            i.width AS image_width,
            i.height AS image_height,
            i.bbox_json AS image_bbox,
            i.page_image_index
        FROM card_images ci
        JOIN extracted_images i ON i.id = ci.image_id
        WHERE ci.card_id = ?
        ORDER BY ci.sort_order, ci.id
        """,
        (item["card_id"],),
    ):
        image_item = row_to_dict(image)
        image_item["image_url"] = image_url(image_item["file_path"])
        images.append(image_item)
    item["images"] = images
    item["image_count"] = len(images)
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
    conn.execute("DELETE FROM card_images WHERE card_id = ?", (card_id,))
    conn.execute(
        """
        UPDATE cards
        SET caption_text = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (first_caption, card_id),
    )
    conn.execute(
        """
        INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
        VALUES (?, ?, 0, ?)
        """,
        (card_id, first["image_id"], first_caption),
    )
    for image in images[1:]:
        caption = image["source_caption_text"] or card["caption_text"]
        cursor = conn.execute(
            """
            INSERT INTO cards
                (document_id, caption_block_id, source_page, caption_text, confidence, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                card["document_id"],
                card["caption_block_id"],
                image["page_number"],
                caption,
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


def render_pdf_crop(conn: sqlite3.Connection, card_ids: list[int]) -> dict:
    try:
        import fitz
    except ModuleNotFoundError as error:
        raise RuntimeError("PyMuPDF is required for PDF crop previews") from error

    rows = conn.execute(
        f"""
        SELECT
            c.id AS card_id,
            c.document_id,
            i.page_number,
            i.bbox_json,
            d.source_path
        FROM cards c
        JOIN card_images ci ON ci.card_id = c.id
        JOIN extracted_images i ON i.id = ci.image_id
        JOIN documents d ON d.id = c.document_id
        WHERE c.id IN ({','.join('?' for _ in card_ids)})
        ORDER BY c.source_page, c.id, ci.sort_order
        """,
        card_ids,
    ).fetchall()
    if not rows:
        raise LookupError("No cards found")
    pages = {int(row["page_number"]) for row in rows}
    sources = {row["source_path"] for row in rows}
    if len(pages) != 1 or len(sources) != 1:
        raise ValueError("PDF crop preview supports cards on one page")
    boxes = [json.loads(row["bbox_json"]) for row in rows]
    x0 = min(float(box["x0"]) for box in boxes)
    y0 = min(float(box["y0"]) for box in boxes)
    x1 = max(float(box["x1"]) for box in boxes)
    y1 = max(float(box["y1"]) for box in boxes)
    pdf = fitz.open(next(iter(sources)))
    page = pdf.load_page(next(iter(pages)) - 1)
    clip = fitz.Rect(
        max(page.rect.x0, x0 - 28),
        max(page.rect.y0, y0 - 28),
        min(page.rect.x1, x1 + 28),
        min(page.rect.y1, y1 + 28),
    )
    digest = hashlib.sha1(",".join(map(str, card_ids)).encode("utf-8")).hexdigest()[:12]
    out_dir = Path("assets") / "generated" / "pdf-crops"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"cards-{digest}.png"
    page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False).save(out_path)
    return {
        "card_ids": card_ids,
        "page_number": next(iter(pages)),
        "image_url": image_url(str(out_path)),
    }


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
