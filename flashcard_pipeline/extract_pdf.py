from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .caption_repair import apply_caption_repairs
from .db import DEFAULT_DB_PATH, connect, init_db

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - exercised by CLI users without deps
    fitz = None


CAPTION_RE = re.compile(
    r"(^|\s)(그림|Fig\.?|Figure|Table|표)\s*[\dIVXivx가-힣\-\.]*",
    re.IGNORECASE,
)
NUMBERED_RE = re.compile(r"^\s*(\(?\d+[\-\.\)]|\d+\s*[A-Z]?\.|[A-Z]\.|\([a-z]\))")


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_json(self) -> str:
        return json.dumps(
            {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1},
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class TextBlock:
    db_id: int
    page_number: int
    block_number: int
    text: str
    rect: Rect


@dataclass(frozen=True)
class CaptionMatch:
    block: TextBlock | None
    confidence: float
    reason: str


@dataclass(frozen=True)
class ExtractedImageData:
    image_bytes: bytes
    ext: str
    width: int
    height: int
    mode: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def document_id_for(file_hash: str) -> str:
    return file_hash[:16]


def horizontal_overlap_ratio(a: Rect, b: Rect) -> float:
    overlap = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return overlap / max(1.0, min(a.width, b.width))


def vertical_overlap_ratio(a: Rect, b: Rect) -> float:
    overlap = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return overlap / max(1.0, min(a.height, b.height))


def score_caption(image_rect: Rect, block: TextBlock) -> tuple[float, str]:
    text = block.text
    if not text:
        return 0.0, "empty"
    has_caption_marker = bool(CAPTION_RE.search(text))
    has_numbered_marker = bool(NUMBERED_RE.search(text))

    h_overlap = horizontal_overlap_ratio(image_rect, block.rect)
    v_overlap = vertical_overlap_ratio(image_rect, block.rect)
    below_gap = block.rect.y0 - image_rect.y1
    above_gap = image_rect.y0 - block.rect.y1
    left_gap = image_rect.x0 - block.rect.x1
    right_gap = block.rect.x0 - image_rect.x1

    score = 0.0
    reasons: list[str] = []

    if -8 <= below_gap <= 150 and h_overlap >= 0.25:
        proximity = max(0.0, 1.0 - max(0.0, below_gap) / 150.0)
        score += 0.48 + 0.22 * proximity + 0.15 * h_overlap
        reasons.append("below")
    elif -8 <= above_gap <= 90 and h_overlap >= 0.25:
        proximity = max(0.0, 1.0 - max(0.0, above_gap) / 90.0)
        score += 0.30 + 0.15 * proximity + 0.10 * h_overlap
        reasons.append("above")
    elif -8 <= right_gap <= 120 and v_overlap >= 0.20:
        proximity = max(0.0, 1.0 - max(0.0, right_gap) / 120.0)
        score += 0.28 + 0.14 * proximity + 0.10 * v_overlap
        reasons.append("right")
    elif -8 <= left_gap <= 120 and v_overlap >= 0.20:
        proximity = max(0.0, 1.0 - max(0.0, left_gap) / 120.0)
        score += 0.28 + 0.14 * proximity + 0.10 * v_overlap
        reasons.append("left")

    if has_caption_marker:
        score += 0.18
        reasons.append("caption-keyword")
    if has_numbered_marker:
        score += 0.06
        reasons.append("numbered")
    if 8 <= len(text) <= 260:
        score += 0.06
        reasons.append("length")
    elif len(text) > 520:
        score -= 0.18
        reasons.append("too-long")

    if not has_caption_marker and not has_numbered_marker:
        score = min(score, 0.20)
        reasons.append("no-caption-marker")
    if len(text) <= 2:
        score = min(score, 0.10)
        reasons.append("too-short")

    return max(0.0, min(1.0, score)), ",".join(reasons) or "weak"


def match_caption(image_rect: Rect, blocks: Iterable[TextBlock]) -> CaptionMatch:
    best_block: TextBlock | None = None
    best_score = 0.0
    best_reason = ""

    for block in blocks:
        score, reason = score_caption(image_rect, block)
        if score > best_score:
            best_block = block
            best_score = score
            best_reason = reason

    return CaptionMatch(best_block, round(best_score, 4), best_reason)


def meaningful_image(width: int, height: int, min_width: int, min_height: int, min_area: int) -> bool:
    return width >= min_width and height >= min_height and (width * height) >= min_area


def render_scale_for(rect: Rect, source_width: int, source_height: int, max_scale: float) -> float:
    if rect.width <= 0 or rect.height <= 0:
        return 1.0
    native_scale = max(source_width / rect.width, source_height / rect.height)
    return max(1.0, min(max_scale, native_scale))


def pixmap_to_png_data(pixmap) -> ExtractedImageData:
    try:
        image_bytes = pixmap.tobytes("png")
        return ExtractedImageData(
            image_bytes=image_bytes,
            ext="png",
            width=int(pixmap.width),
            height=int(pixmap.height),
            mode="raw",
        )
    except Exception:
        pass

    color_spaces = [fitz.csGRAY] if pixmap.n == 1 else []
    color_spaces.append(fitz.csRGB)
    for color_space in color_spaces:
        converted = fitz.Pixmap(color_space, pixmap)
        try:
            image_bytes = converted.tobytes("png")
        except Exception:
            continue
        return ExtractedImageData(
            image_bytes=image_bytes,
            ext="png",
            width=int(converted.width),
            height=int(converted.height),
            mode="raw",
        )

    raise ValueError("Could not convert PDF image object to PNG")


def extract_raw_image_data(pdf, xref: int) -> ExtractedImageData:
    pixmap = fitz.Pixmap(pdf, xref)
    return pixmap_to_png_data(pixmap)


def extract_rendered_image_data(
    page,
    rect,
    source_width: int,
    source_height: int,
    max_render_scale: float,
) -> ExtractedImageData:
    logical_rect = Rect(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
    scale = render_scale_for(logical_rect, source_width, source_height, max_render_scale)
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        clip=rect,
        alpha=False,
    )
    return ExtractedImageData(
        image_bytes=pixmap.tobytes("png"),
        ext="png",
        width=int(pixmap.width),
        height=int(pixmap.height),
        mode="rendered",
    )


def ensure_no_existing_document(conn, document_id: str, replace: bool, assets_root: Path) -> None:
    exists = conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not exists:
        return
    if not replace:
        raise SystemExit(
            f"Document {document_id} already exists. Re-run with --replace to re-import it."
        )
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()
    doc_assets = assets_root / document_id
    if doc_assets.exists():
        shutil.rmtree(doc_assets)


def insert_text_blocks(conn, document_id: str, page_number: int, page) -> list[TextBlock]:
    text_blocks: list[TextBlock] = []
    for raw in page.get_text("blocks"):
        if len(raw) < 7:
            continue
        x0, y0, x1, y1, text, block_number, block_type = raw[:7]
        if block_type != 0:
            continue
        cleaned = clean_text(text)
        if not cleaned:
            continue
        rect = Rect(float(x0), float(y0), float(x1), float(y1))
        cursor = conn.execute(
            """
            INSERT INTO extracted_text_blocks
                (document_id, page_number, block_number, text, bbox_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (document_id, page_number, int(block_number), cleaned, rect.to_json()),
        )
        text_blocks.append(
            TextBlock(
                db_id=int(cursor.lastrowid),
                page_number=page_number,
                block_number=int(block_number),
                text=cleaned,
                rect=rect,
            )
        )
    return text_blocks


def import_pdf(
    pdf_path: Path,
    db_path: Path,
    assets_root: Path,
    max_pages: int | None,
    replace: bool,
    min_image_width: int,
    min_image_height: int,
    min_image_area: int,
    min_caption_confidence: float,
    max_render_scale: float,
    image_mode: str,
) -> dict:
    if fitz is None:
        raise SystemExit(
            "PyMuPDF is not installed. Run: python -m pip install -r requirements.txt"
        )
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    file_hash = sha256_file(pdf_path)
    document_id = document_id_for(file_hash)
    assets_root = assets_root / "pdf"

    conn = connect(db_path)
    init_db(conn)
    ensure_no_existing_document(conn, document_id, replace, assets_root)

    pdf = fitz.open(str(pdf_path))
    page_count = len(pdf) if max_pages is None else min(len(pdf), max_pages)

    summary = {
        "document_id": document_id,
        "pages": page_count,
        "images": 0,
        "duplicates": 0,
        "raw_images": 0,
        "rendered_images": 0,
        "raw_fallbacks": 0,
        "text_blocks": 0,
        "cards": 0,
        "image_mode": image_mode,
        "db_path": str(db_path),
        "assets_root": str(assets_root),
    }

    conn.execute(
        """
        INSERT INTO documents (id, source_path, filename, file_hash, file_size)
        VALUES (?, ?, ?, ?, ?)
        """,
        (document_id, str(pdf_path.resolve()), pdf_path.name, file_hash, pdf_path.stat().st_size),
    )

    seen_hashes: dict[str, int] = {}
    raw_cache: dict[int, ExtractedImageData | None] = {}

    for page_index in range(page_count):
        page = pdf[page_index]
        page_number = page_index + 1
        conn.execute(
            """
            INSERT INTO pdf_pages (document_id, page_number, width, height)
            VALUES (?, ?, ?, ?)
            """,
            (document_id, page_number, float(page.rect.width), float(page.rect.height)),
        )

        text_blocks = insert_text_blocks(conn, document_id, page_number, page)
        summary["text_blocks"] += len(text_blocks)

        page_dir = assets_root / document_id / f"page-{page_number}"
        page_dir.mkdir(parents=True, exist_ok=True)
        page_image_index = 0

        for image_info in page.get_images(full=True):
            xref = int(image_info[0])
            rects = page.get_image_rects(xref)
            if not rects:
                continue
            source_width = int(image_info[2] or 0)
            source_height = int(image_info[3] or 0)

            for rect_index, fitz_rect in enumerate(rects):
                page_image_index += 1
                rect = Rect(
                    float(fitz_rect.x0),
                    float(fitz_rect.y0),
                    float(fitz_rect.x1),
                    float(fitz_rect.y1),
                )
                image_data: ExtractedImageData | None = None
                if image_mode == "raw":
                    if xref not in raw_cache:
                        try:
                            raw_cache[xref] = extract_raw_image_data(pdf, xref)
                        except Exception:
                            raw_cache[xref] = None
                    image_data = raw_cache[xref]

                if image_data is None:
                    if image_mode == "raw":
                        summary["raw_fallbacks"] += 1
                    image_data = extract_rendered_image_data(
                        page,
                        fitz_rect,
                        source_width,
                        source_height,
                        max_render_scale,
                    )

                if image_data.mode == "raw":
                    summary["raw_images"] += 1
                else:
                    summary["rendered_images"] += 1

                image_bytes = image_data.image_bytes
                image_hash = sha256_bytes(image_bytes)
                ext = image_data.ext
                width = image_data.width
                height = image_data.height
                duplicate_of = seen_hashes.get(image_hash)
                is_duplicate = duplicate_of is not None
                if is_duplicate:
                    summary["duplicates"] += 1
                    original = conn.execute(
                        "SELECT file_path FROM extracted_images WHERE id = ?",
                        (duplicate_of,),
                    ).fetchone()
                    image_path = (
                        Path(original["file_path"])
                        if original
                        else page_dir / f"image-{xref}-{rect_index + 1}.{ext}"
                    )
                else:
                    if image_data.mode == "raw":
                        image_path = page_dir / f"image-{xref}.{ext}"
                    else:
                        image_path = page_dir / f"image-{xref}-{rect_index + 1}.{ext}"
                    image_path.write_bytes(image_bytes)

                cursor = conn.execute(
                    """
                    INSERT INTO extracted_images
                        (
                            document_id, page_number, page_image_index, xref,
                            file_path, file_hash, ext, width, height, bbox_json,
                            is_duplicate, duplicate_of
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        page_number,
                        page_image_index,
                        xref,
                        str(image_path),
                        image_hash,
                        ext,
                        width,
                        height,
                        rect.to_json(),
                        1 if is_duplicate else 0,
                        duplicate_of,
                    ),
                )
                image_id = int(cursor.lastrowid)
                if not is_duplicate:
                    seen_hashes[image_hash] = image_id
                summary["images"] += 1

                if not meaningful_image(width, height, min_image_width, min_image_height, min_image_area):
                    continue

                match = match_caption(rect, text_blocks)
                caption = match.block.text if match.block else ""
                notes = f"caption_match={match.reason}; image_mode={image_data.mode}"
                if match.confidence < min_caption_confidence:
                    notes += "; low_caption_confidence=1"
                cursor = conn.execute(
                    """
                    INSERT INTO cards
                        (
                            document_id, caption_block_id, source_page,
                            caption_text, confidence, notes
                        )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        match.block.db_id if match.block else None,
                        page_number,
                        caption,
                        match.confidence,
                        notes,
                    ),
                )
                card_id = int(cursor.lastrowid)
                conn.execute(
                    """
                    INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
                    VALUES (?, ?, 0, ?)
                    """,
                    (
                        card_id,
                        image_id,
                        caption,
                    ),
                )
                summary["cards"] += 1

        conn.commit()

    repair_summary = apply_caption_repairs(conn, document_id=document_id)
    summary["caption_repairs"] = repair_summary["repaired_cards"]
    summary["caption_label_groups"] = repair_summary["caption_label_groups"]
    summary["caption_label_updates"] = repair_summary["caption_label_updates"]

    conn.close()
    pdf.close()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract PDF images into flashcard cards.")
    parser.add_argument("pdf", type=Path, help="Source PDF path")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--assets", type=Path, default=Path("assets"), help="Asset output root")
    parser.add_argument("--max-pages", type=int, default=None, help="Import only the first N pages")
    parser.add_argument("--replace", action="store_true", help="Replace existing import for same PDF hash")
    parser.add_argument("--min-image-width", type=int, default=80)
    parser.add_argument("--min-image-height", type=int, default=80)
    parser.add_argument("--min-image-area", type=int, default=6400)
    parser.add_argument("--min-caption-confidence", type=float, default=0.25)
    parser.add_argument(
        "--max-render-scale",
        type=float,
        default=6.0,
        help="Maximum PDF render scale for saved image crops.",
    )
    parser.add_argument(
        "--image-mode",
        choices=("raw", "rendered"),
        default="raw",
        help=(
            "Use normalized PDF image objects when possible, or render page crops "
            "with the previous extraction strategy."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = import_pdf(
        pdf_path=args.pdf,
        db_path=args.db,
        assets_root=args.assets,
        max_pages=args.max_pages,
        replace=args.replace,
        min_image_width=args.min_image_width,
        min_image_height=args.min_image_height,
        min_image_area=args.min_image_area,
        min_caption_confidence=args.min_caption_confidence,
        max_render_scale=args.max_render_scale,
        image_mode=args.image_mode,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
