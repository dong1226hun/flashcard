# Flashcard PDF Importer

Local pipeline for extracting embedded PDF images, nearby captions, and study-ready flashcard cards.

## Setup

```powershell
python -m pip install -r requirements.txt
```

## Import a PDF

Import all pages:

```powershell
python -m flashcard_pipeline.extract_pdf "150727_영상치의학5차교정-final (1).pdf"
```

Import a small sample first:

```powershell
python -m flashcard_pipeline.extract_pdf "150727_영상치의학5차교정-final (1).pdf" --max-pages 10 --replace
```

Default outputs:

- SQLite DB: `data/flashcards.sqlite`
- Raw-normalized image objects: `assets/pdf/{documentId}/page-{n}/image-{xref}.png`

Use the previous page-rendered crop strategy when you need it:

```powershell
python -m flashcard_pipeline.extract_pdf "150727_영상치의학5차교정-final (1).pdf" --image-mode rendered --replace
```

## Study And Manage Cards

```powershell
python -m flashcard_pipeline.review_server
```

Then open:

```text
http://127.0.0.1:8765
```

- `/`: flashcard study UI
- `/review`: card admin UI for caption/notes edits, favorite/past-exam toggles, PDF crop checks, delete, merge, and split

## GitHub Pages Export

Build a static, read-only study site in `docs/`:

```powershell
python -m flashcard_pipeline.export_pages
```

Then configure GitHub Pages to publish from the `docs/` folder. The export copies only the referenced card images into `docs/assets/` and writes the study data to `docs/data/cards.json`. Static favorite and correct/wrong state is stored in each browser's `localStorage`; admin edits still require the local review server.

## Data Model

- `documents`: source PDF metadata
- `pdf_pages`: page number and dimensions
- `extracted_images`: extracted PDF image objects and placements
- `extracted_text_blocks`: text layer blocks with coordinates
- `cards`: current study/admin cards
- `card_images`: one or more extracted images attached to each card
- `study_favorites`, `study_past_exams`, `study_reviews`: study metadata keyed by `card_id`

## Notes

This pipeline uses PDF-native text extraction and raw-normalized PDF image objects by default. PyMuPDF converts PDF-specific color spaces such as `/Separation /Black` to standard PNG output so image objects can be saved without nearby page text. The older rendered crop mode is still available with `--image-mode rendered`.

OCR should only be added later for captions that are baked into image pixels and missing from the PDF text layer.
