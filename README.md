# 플래시카드 웹 템플릿

PDF에서 이미지와 캡션을 추출해 플래시카드 데이터베이스를 만들고, 같은 학습 UI를 로컬 서버와 정적 페이지에서 모두 사용할 수 있게 만든 프로젝트입니다.

현재 구조의 핵심 목표는 다음과 같습니다.

- 원본 데이터는 `data/flashcards.sqlite`와 `data/media/`에만 둔다.
- 서버용 앱과 정적 배포 앱이 같은 카드 스키마와 같은 프론트엔드 런타임을 공유한다.
- 이미지형, 객관식, 주관식 카드를 같은 방식으로 렌더링한다.
- `docs/`는 직접 수정하는 원본이 아니라 `export_pages`로 만드는 정적 배포 결과물로 취급한다.

## 빠른 시작

```powershell
python -m pip install -r requirements.txt
python -m flashcard_pipeline.review_server
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8765
```

주요 화면은 두 개입니다.

- `/`: 플래시카드 학습 화면
- `/review`: 카드 관리 화면

## 프로젝트 구조

```text
flashcard/
  data/
    flashcards.sqlite
    media/
      pdf/
      generated/

  flashcard_pipeline/
    static/
      index.html
      review.html
      app.js
      fonts/
      styles/
      study/
    db.py
    extract_pdf.py
    export_pages.py
    media.py
    media_cleanup.py
    review_server.py
    study.py

  docs/
    index.html
    data/
    static/
    media/

  tests/
```

각 폴더의 역할은 아래처럼 나뉩니다.

| 경로 | 역할 |
| --- | --- |
| `data/flashcards.sqlite` | 카드, 답안, 리뷰 상태, PDF 메타데이터가 저장되는 원본 SQLite DB |
| `data/media/` | PDF에서 추출한 원본 이미지와 생성 이미지가 저장되는 원본 미디어 폴더 |
| `flashcard_pipeline/static/` | 서버와 정적 export가 공유하는 프론트엔드 원본 |
| `flashcard_pipeline/static/study/` | 학습 화면 JS 런타임, provider, renderer, theme 모듈 |
| `flashcard_pipeline/static/styles/` | 공통 디자인 토큰과 화면별 CSS |
| `docs/` | 정적 배포용 생성물. 직접 수정하지 않고 `export_pages`로 재생성 |
| `tests/` | 데이터 변환, 학습 세션, export, 관리 기능 테스트 |

## 데이터 원본 정책

이 프로젝트에서 원본은 두 곳뿐입니다.

```text
data/flashcards.sqlite
data/media/
```

답안 원본은 SQLite의 `cards.answer_text`에 저장됩니다. 이미지 원본은 `data/media/` 아래에 저장됩니다.

`docs/data/cards.json`과 `docs/media/`는 정적 배포용 복사본입니다. 정적 페이지는 서버가 없으므로 브라우저가 직접 접근할 수 있는 `docs/media/...` 이미지 파일이 필요합니다. 따라서 `docs/media/`는 중복 원본이 아니라 배포 산출물입니다.

## 카드 스키마

학습 UI는 아래 형태의 명시적 카드 스키마를 기준으로 동작합니다.

```json
{
  "id": "card-1",
  "type": "image",
  "prompt": {
    "text": "문제 지문"
  },
  "media": [
    {
      "kind": "image",
      "src": "/media/pdf/document-id/page-1/image-1.png",
      "alt": "이미지 설명"
    }
  ],
  "choices": [
    {
      "id": "a",
      "text": "선택지 A"
    }
  ],
  "answer": {
    "text": "정답 텍스트",
    "choiceIds": ["a"],
    "explanation": "해설"
  },
  "meta": {
    "chapter": "단원명",
    "sourcePage": 1,
    "tags": ["태그"]
  },
  "review": {
    "favorite": false,
    "pastExam": false,
    "lastResult": "wrong"
  }
}
```

지원하는 카드 타입은 세 가지입니다.

| 타입 | 설명 |
| --- | --- |
| `image` | 이미지와 문제를 보여주고 reveal 후 답안과 해설 표시 |
| `multiple_choice` | 선택지를 렌더링하고 reveal 후 정답 선택지 표시. `choiceIds` 배열로 단일/복수 정답 지원 |
| `short_answer` | 사용자가 답을 입력하거나 머릿속으로 푼 뒤 reveal. 자동 채점 대신 자기평가 사용 |

## 프론트엔드 구조

학습 화면은 `flashcard_pipeline/static/study/` 아래 모듈로 나뉩니다.

```text
study/
  main.js
  providers.js
  renderers.js
  theme.js
```

| 파일 | 역할 |
| --- | --- |
| `main.js` | 앱 초기화, 이벤트 연결, 세션 상태, 키보드 이동, reveal 흐름 |
| `providers.js` | 서버 API provider와 static JSON provider. 두 실행 환경을 같은 카드 배열로 정규화 |
| `renderers.js` | `image`, `multiple_choice`, `short_answer` 타입별 DOM 렌더링 |
| `theme.js` | Light/Dark 테마 초기화와 토글 |

디자인 CSS는 아래처럼 분리되어 있습니다.

```text
styles/
  tokens.css
  base.css
  study.css
  admin.css
```

| 파일 | 역할 |
| --- | --- |
| `tokens.css` | Pretendard 폰트 선언과 공통 폰트 스택 |
| `base.css` | 공통 box sizing, 폼 요소 폰트 상속, `.hidden` |
| `study.css` | 플래시카드 학습 화면 전용 레이아웃과 색상 |
| `admin.css` | 카드 관리 화면 전용 레이아웃과 색상 |

`flashcard_pipeline/static/`은 프론트엔드 원본이고, `docs/static/`은 export 결과물입니다. 디자인이나 JS를 수정할 때는 항상 `flashcard_pipeline/static/`을 수정한 뒤 export를 다시 실행합니다.

## PDF 가져오기

PDF를 가져오면 SQLite DB와 `data/media/`에 카드 데이터와 이미지가 생성됩니다.

```powershell
python -m flashcard_pipeline.extract_pdf "자료.pdf"
```

일부 페이지만 테스트로 가져올 때:

```powershell
python -m flashcard_pipeline.extract_pdf "자료.pdf" --max-pages 10 --replace
```

이미 가져온 같은 PDF를 다시 가져올 때:

```powershell
python -m flashcard_pipeline.extract_pdf "자료.pdf" --replace
```

기본 이미지 저장 방식은 PDF 내부 이미지 객체를 정규화해 저장하는 `raw` 모드입니다.

```powershell
python -m flashcard_pipeline.extract_pdf "자료.pdf" --image-mode raw
```

예전 방식처럼 페이지 영역을 렌더링해서 crop 이미지로 저장해야 할 때는 `rendered` 모드를 사용합니다.

```powershell
python -m flashcard_pipeline.extract_pdf "자료.pdf" --image-mode rendered --replace
```

주요 옵션은 다음과 같습니다.

| 옵션 | 설명 |
| --- | --- |
| `--db` | 사용할 SQLite DB 경로. 기본값은 `data/flashcards.sqlite` |
| `--assets` | 미디어 저장 루트. 기본값은 `data/media` |
| `--max-pages` | 앞에서 N페이지만 가져오기 |
| `--replace` | 같은 PDF hash로 가져온 기존 데이터를 지우고 다시 가져오기 |
| `--image-mode raw` | PDF 내부 이미지 객체를 추출해 PNG로 저장 |
| `--image-mode rendered` | 페이지를 렌더링한 뒤 이미지 영역을 crop |
| `--min-caption-confidence` | 캡션 매칭 최소 신뢰도 |

## 로컬 서버 실행

```powershell
python -m flashcard_pipeline.review_server --open
```

브라우저가 자동으로 열리지 않으면 터미널에 출력된 주소를 직접 엽니다. 서버가 실행되는 동안 터미널은 계속 열린 상태로 대기하며, 종료하려면 `Ctrl+C`를 누릅니다. 기본 주소는 다음과 같습니다.

```text
http://127.0.0.1:8765
```

기본 포트가 이미 사용 중이면 서버가 자동으로 다음 포트를 찾아 실행하고 실제 주소를 출력합니다.

포트를 바꾸고 싶으면:

```powershell
python -m flashcard_pipeline.review_server --port 8770
```

다른 DB를 사용하고 싶으면:

```powershell
python -m flashcard_pipeline.review_server --db data/flashcards.sqlite
```

서버는 아래 경로를 제공합니다.

| 경로 | 설명 |
| --- | --- |
| `/` | 학습 화면 |
| `/review` | 카드 관리 화면 |
| `/static/...` | `flashcard_pipeline/static/`의 CSS, JS, font |
| `/media/...` | `data/media/`의 이미지 |
| `/api/study/session` | 학습 세션 생성 |
| `/api/study/sections` | 학습 필터와 섹션 정보 |
| `/api/study/review` | 정답/오답/애매함 자기평가 저장 |
| `/api/study/favorite` | 즐겨찾기 토글 |
| `/api/study/past-exam` | 기출 표시 토글 |
| `/api/cards` | 관리 화면 카드 목록 |

## 정적 페이지 export

정적 페이지는 `docs/`에 생성됩니다.

```powershell
python -m flashcard_pipeline.export_pages --clean
```

생성 결과:

```text
docs/
  index.html
  data/
    cards.json
    sections.json
  static/
    fonts/
    styles/
    study/
  media/
```

정적 export의 규칙은 다음과 같습니다.

- `docs/data/cards.json`에는 내부 파일 시스템 경로를 넣지 않는다.
- 정적 카드 이미지 경로는 `media/...` 상대 URL로 기록한다.
- 실제 이미지 파일은 `docs/media/...`로 복사한다.
- `docs/static/...`은 `flashcard_pipeline/static/...`에서 복사한다.
- 정적 페이지에서는 서버 DB에 쓰기 작업을 할 수 없으므로 즐겨찾기와 리뷰 상태는 브라우저 `localStorage`에 저장된다.

다른 위치에 export하고 싶으면:

```powershell
python -m flashcard_pipeline.export_pages --output docs --clean
```

GitHub Pages 배포는 `.github/workflows/pages.yml`에 정의되어 있습니다. 현재 워크플로는 수동 실행 방식입니다.

## 관리 화면에서 하는 일

`/review` 화면은 카드 데이터를 정리하기 위한 로컬 관리 UI입니다.

주요 기능:

- 카드 지문, 답안, 메모 수정
- 즐겨찾기 표시
- 기출 표시
- 카드 삭제
- 카드 병합
- 카드 분할

관리 화면에서 수정한 내용은 SQLite DB에 저장됩니다. 따라서 정적 배포용 `docs/`만 열어서는 관리 기능을 사용할 수 없습니다.

## 학습 화면 동작

학습 화면의 기본 흐름은 다음과 같습니다.

1. provider가 카드 배열을 로드한다.
2. 현재 카드 타입에 맞는 renderer가 문제 영역을 그린다.
3. 사용자가 답을 생각하거나 선택지를 고른다.
4. reveal 후 정답과 해설을 확인한다.
5. `맞음`, `틀림`, `애매함` 중 하나로 자기평가한다.
6. 서버 모드에서는 DB에 기록하고, 정적 모드에서는 브라우저 `localStorage`에 기록한다.

이미지 카드는 고정된 이미지 stage 안에서 `object-fit: contain` 방식으로 표시됩니다. 그래서 세로 이미지나 길쭉한 이미지도 잘리지 않고 전체가 보이도록 유지됩니다.

## 미디어 경로 정책

서버 모드와 정적 모드는 URL 정책이 다릅니다.

| 환경 | 이미지 URL | 실제 파일 위치 |
| --- | --- | --- |
| 로컬 서버 | `/media/pdf/...` | `data/media/pdf/...` |
| 정적 페이지 | `media/pdf/...` | `docs/media/pdf/...` |

DB에는 파일 시스템 경로인 `data/media/...`가 저장됩니다. 프론트엔드에는 `/media/...` 또는 `media/...` URL만 노출됩니다.

## 미디어 경로 정리

예전 `assets/`, `docs/assets/` 구조가 남아 있는 DB를 정리할 때는 아래 명령을 사용합니다.

```powershell
python -m flashcard_pipeline.media_cleanup
```

이 명령은 DB에 기록된 미디어 경로를 `data/media/...` 기준으로 옮기고, 검증 후 legacy asset 폴더를 삭제합니다.

legacy 폴더를 삭제하지 않고 경로만 옮기고 싶으면:

```powershell
python -m flashcard_pipeline.media_cleanup --keep-legacy
```

## 캡션 보정 도구

PDF 캡션 매칭을 보정하는 보조 도구가 있습니다.

캡션 보정 후보만 확인:

```powershell
python -m flashcard_pipeline.caption_repair --dry-run
```

캡션 보정 적용:

```powershell
python -m flashcard_pipeline.caption_repair
```

반복되는 figure caption에 패널 라벨을 붙일 때:

```powershell
python -m flashcard_pipeline.caption_labels
```

특정 문서만 대상으로 실행하려면 `--document-id`를 사용합니다.

```powershell
python -m flashcard_pipeline.caption_repair --document-id 문서ID
```

## 테스트

전체 테스트:

```powershell
python -m pytest -q tests -p no:cacheprovider
```

JS 문법 검사:

```powershell
node --check flashcard_pipeline/static/study/main.js
node --check flashcard_pipeline/static/study/providers.js
node --check flashcard_pipeline/static/study/renderers.js
node --check flashcard_pipeline/static/study/theme.js
node --check flashcard_pipeline/static/app.js
```

정적 export 확인:

```powershell
python -m flashcard_pipeline.export_pages --clean
```

확인할 항목:

- `docs/index.html`이 `./static/styles/study.css`를 참조하는지
- `docs/data/cards.json`에 `file_path`가 남아 있지 않은지
- `docs/data/cards.json`의 이미지 경로가 `media/...`인지
- `docs/media/...`에 실제 이미지가 복사되었는지

## 개발 규칙

이 프로젝트를 수정할 때는 아래 원칙을 지킵니다.

- 원본 데이터는 `data/flashcards.sqlite`와 `data/media/`만 기준으로 본다.
- `docs/`는 생성물이므로 직접 수정하지 않는다.
- 프론트엔드 원본은 `flashcard_pipeline/static/`에서만 수정한다.
- 정적 페이지를 갱신할 때는 `python -m flashcard_pipeline.export_pages --clean`을 실행한다.
- 새 카드 타입을 추가할 때는 schema, provider normalization, renderer, tests를 함께 수정한다.
- 런타임 렌더링에서 legacy 필드 추론을 늘리지 않는다.

## 삭제해도 되는 파일

다음 파일은 실행 중 생기는 캐시나 로그이므로 삭제해도 됩니다.

```text
__pycache__/
tests/__pycache__/
.pytest_cache/
pytest-cache-files-*/
tmp/
*.log
```

마이그레이션 백업 DB도 앱 실행에는 필요하지 않습니다.

```text
data/flashcards.sqlite.before_*
data/flashcards_raw.sqlite
```

다만 큰 마이그레이션 직후에는 결과를 충분히 확인한 뒤 삭제하는 편이 안전합니다.

## 자주 헷갈리는 부분

### `flashcard_pipeline/static`과 `docs/static`의 차이

`flashcard_pipeline/static`은 원본 프론트엔드 코드입니다. 로컬 서버가 `/static/...`으로 이 파일들을 제공합니다.

`docs/static`은 정적 배포용 복사본입니다. `export_pages`를 실행하면 원본 프론트엔드 코드가 이곳으로 복사됩니다.

### `data/media`와 `docs/media`의 차이

`data/media`는 원본 이미지 저장소입니다.

`docs/media`는 정적 배포용 이미지 복사본입니다. 정적 페이지는 로컬 서버 없이 동작해야 하므로 `docs/media`가 필요합니다.

### 서버 모드와 정적 모드의 차이

서버 모드는 SQLite DB에 즐겨찾기, 기출 표시, 리뷰 기록을 저장합니다.

정적 모드는 DB를 수정할 수 없으므로 브라우저 `localStorage`에 즐겨찾기와 리뷰 상태를 저장합니다.

## 현재 남겨야 하는 핵심 파일

최소 운영 기준으로 중요한 파일은 다음입니다.

```text
data/flashcards.sqlite
data/media/
flashcard_pipeline/
tests/
requirements.txt
README.md
```

정적 배포를 사용할 경우에는 아래도 필요합니다.

```text
docs/
.github/workflows/pages.yml
```
