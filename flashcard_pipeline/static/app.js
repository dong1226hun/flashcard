const THEME_STORAGE_KEY = "flashcard-theme";

function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function applyTheme(theme) {
  const nextTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = nextTheme;
  document.documentElement.style.colorScheme = nextTheme;
  const toggle = document.querySelector("#theme-toggle");
  if (toggle) {
    const label = toggle.querySelector(".theme-toggle-text");
    if (label) label.textContent = nextTheme === "dark" ? "Dark" : "Light";
    toggle.setAttribute("aria-pressed", String(nextTheme === "dark"));
    toggle.setAttribute("aria-checked", String(nextTheme === "dark"));
    toggle.setAttribute("title", nextTheme === "dark" ? "Switch to light mode" : "Switch to dark mode");
  }
}

function initThemeToggle() {
  applyTheme(currentTheme());
  const toggle = document.querySelector("#theme-toggle");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    const nextTheme = currentTheme() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch {
      // Theme still changes for this page if localStorage is unavailable.
    }
    applyTheme(nextTheme);
  });
}

initThemeToggle();

const state = {
  limit: 25,
  offset: 0,
  total: 0,
  selected: new Set(),
  filters: {
    q: "",
    chapter: "",
    page: "",
    figure: "",
    pastExam: false,
    multi: false,
  },
};

const els = {
  list: document.querySelector("#card-list"),
  documentCount: document.querySelector("#document-count"),
  viewTitle: document.querySelector("#view-title"),
  pageLabel: document.querySelector("#page-label"),
  prev: document.querySelector("#prev"),
  next: document.querySelector("#next"),
  refresh: document.querySelector("#refresh"),
  pageSize: document.querySelector("#page-size"),
  mergeSelected: document.querySelector("#merge-selected"),
  cropSelected: document.querySelector("#crop-selected"),
  cropPreview: document.querySelector("#crop-preview"),
  toast: document.querySelector("#toast"),
  query: document.querySelector("#query"),
  chapter: document.querySelector("#chapter"),
  page: document.querySelector("#page"),
  figure: document.querySelector("#figure"),
  pastExamOnly: document.querySelector("#past-exam-only"),
  multiOnly: document.querySelector("#multi-only"),
  applyFilters: document.querySelector("#apply-filters"),
  metrics: {
    cards: document.querySelector("#metric-cards"),
    favorites: document.querySelector("#metric-favorites"),
    pastExams: document.querySelector("#metric-past-exams"),
    multi: document.querySelector("#metric-multi"),
  },
};

let toastTimer;

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function showToast(message) {
  clearTimeout(toastTimer);
  els.toast.textContent = message;
  els.toast.classList.add("show");
  toastTimer = setTimeout(() => els.toast.classList.remove("show"), 2200);
}

function setText(node, text) {
  if (node) node.textContent = text;
}

function button(text, className = "secondary") {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  node.textContent = text;
  return node;
}

function badge(text, className = "") {
  const node = document.createElement("span");
  node.className = `badge${className ? ` ${className}` : ""}`;
  node.textContent = text;
  return node;
}

function figureLabel(item) {
  return item.figure_key ? `그림 ${item.figure_key}` : "그림 미확인";
}

function composeCaption(baseCaption, answerTitle, answerDetail) {
  const title = answerTitle.trim().replace(/\s+/g, " ");
  const detail = answerDetail.trim().replace(/\s+/g, " ");
  let body = detail;
  if (title && detail) {
    body = `${title}${/[.?!]$/.test(title) ? "" : "."} ${detail}`;
  } else if (title) {
    body = title;
  }

  const match = (baseCaption || "").match(/^(?:(?:그림|Fig\.?|Figure)\s*\d+\s*[-‐‑‒–—―－]\s*\d+[A-Za-z]?\s*[.)]?\s*)/i);
  const prefix = match ? match[0].trim() : "";
  return prefix ? `${prefix} ${body}`.trim() : body;
}

function activeFilters() {
  const params = new URLSearchParams({
    limit: String(state.limit),
    offset: String(state.offset),
  });
  if (state.filters.q) params.set("q", state.filters.q);
  if (state.filters.chapter) params.set("chapter", state.filters.chapter);
  if (state.filters.page) params.set("page", state.filters.page);
  if (state.filters.figure) params.set("figure", state.filters.figure);
  if (state.filters.pastExam) params.set("past_exam", "1");
  if (state.filters.multi) params.set("multi", "1");
  return params;
}

function applyFilterInputs() {
  state.filters.q = els.query.value.trim();
  state.filters.chapter = els.chapter.value.trim();
  state.filters.page = els.page.value.trim();
  state.filters.figure = els.figure.value.trim();
  state.filters.pastExam = els.pastExamOnly.checked;
  state.filters.multi = els.multiOnly.checked;
  state.offset = 0;
}

async function loadSummary() {
  const [summary, multi] = await Promise.all([
    fetchJson("/api/study/summary"),
    fetchJson("/api/cards?multi=1&limit=1"),
  ]);
  setText(els.documentCount, `${summary.available_cards} cards`);
  setText(els.metrics.cards, summary.available_cards);
  setText(els.metrics.favorites, summary.favorite_cards);
  setText(els.metrics.pastExams, summary.past_exam_cards);
  setText(els.metrics.multi, multi.total);
}

function renderImages(item, wrap) {
  const images = item.images && item.images.length
    ? item.images
    : [{ image_url: item.image_url, image_width: item.image_width, image_height: item.image_height }];
  wrap.classList.toggle("multi", images.length > 1);
  for (const imageItem of images) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.src = imageItem.image_url;
    image.alt = `Card image from page ${item.source_page}`;
    wrap.appendChild(image);
  }
}

function cardTemplate(item) {
  const article = document.createElement("article");
  article.className = "card-row";
  article.dataset.id = item.card_id;

  const imagePane = document.createElement("div");
  imagePane.className = "image-pane";
  const imageWrap = document.createElement("div");
  imageWrap.className = "image-wrap";
  renderImages(item, imageWrap);
  const imageMeta = document.createElement("div");
  imageMeta.className = "image-meta";
  imageMeta.append(
    badge(figureLabel(item)),
    badge(`p.${item.source_page}`),
    badge(`${item.image_count || 1} img`),
  );
  if (item.is_favorite) imageMeta.appendChild(badge("favorite", "favorite"));
  if (item.is_past_exam) imageMeta.appendChild(badge("기출", "past-exam"));
  imagePane.append(imageWrap, imageMeta);

  const body = document.createElement("div");
  body.className = "card-body-panel";
  const topLine = document.createElement("div");
  topLine.className = "card-topline";

  const selector = document.createElement("label");
  selector.className = "select-card";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.selected.has(Number(item.card_id));
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.selected.add(Number(item.card_id));
    else state.selected.delete(Number(item.card_id));
    updateBulkButtons();
  });
  selector.append(checkbox, document.createTextNode(`#${item.card_id}`));

  const heading = document.createElement("div");
  heading.className = "card-heading";
  const title = document.createElement("strong");
  title.textContent = item.answer_title || figureLabel(item);
  const subtitle = document.createElement("span");
  subtitle.textContent = item.answer_detail || item.caption_text || "caption 없음";
  heading.append(title, subtitle);
  topLine.append(selector, heading);

  const answerFields = document.createElement("div");
  answerFields.className = "answer-fields";
  const answerTitleLabel = document.createElement("label");
  answerTitleLabel.textContent = "대표제목";
  const answerTitle = document.createElement("input");
  answerTitle.className = "answer-title-input";
  answerTitle.value = item.answer_title || "";
  answerTitle.placeholder = "대표제목";
  answerTitleLabel.appendChild(answerTitle);

  const answerDetailLabel = document.createElement("label");
  answerDetailLabel.textContent = "내역";
  const answerDetail = document.createElement("textarea");
  answerDetail.className = "answer-detail-input";
  answerDetail.value = item.answer_detail || "";
  answerDetail.placeholder = "카드 뒷면에 표시할 상세 내역";
  answerDetailLabel.appendChild(answerDetail);
  answerFields.append(answerTitleLabel, answerDetailLabel);

  const captionLabel = document.createElement("label");
  captionLabel.textContent = "Caption";
  const caption = document.createElement("textarea");
  caption.className = "caption";
  caption.value = item.caption_text || "";
  captionLabel.appendChild(caption);

  const notesLabel = document.createElement("label");
  notesLabel.textContent = "Notes";
  const notes = document.createElement("textarea");
  notes.className = "notes";
  notes.value = item.notes || "";
  notesLabel.appendChild(notes);

  const actions = document.createElement("div");
  actions.className = "actions";
  const save = button("저장", "primary");
  const favorite = button(item.is_favorite ? "즐겨찾기 해제" : "즐겨찾기", item.is_favorite ? "exam active" : "secondary");
  const pastExam = button(item.is_past_exam ? "기출 해제" : "기출문제", item.is_past_exam ? "exam active" : "secondary");
  const sameFigure = button("같은 그림", "secondary");
  const crop = button("PDF crop", "secondary");
  const split = button("분리", "warning");
  const remove = button("삭제", "danger");
  split.disabled = Number(item.image_count || 1) <= 1;
  actions.append(save, favorite, pastExam, sameFigure, crop, split, remove);

  const markAnswerEdited = () => {
    article.dataset.answerEdited = "1";
    caption.value = composeCaption(caption.value, answerTitle.value, answerDetail.value);
    title.textContent = answerTitle.value.trim() || figureLabel(item);
    subtitle.textContent = answerDetail.value.trim() || caption.value.trim() || "caption 없음";
  };
  answerTitle.addEventListener("input", markAnswerEdited);
  answerDetail.addEventListener("input", markAnswerEdited);

  save.addEventListener("click", () => saveCard(article).catch((error) => showToast(error.message)));
  favorite.addEventListener("click", () => toggleFavorite(item).catch((error) => showToast(error.message)));
  pastExam.addEventListener("click", () => togglePastExam(item).catch((error) => showToast(error.message)));
  sameFigure.addEventListener("click", () => filterSameFigure(item));
  crop.addEventListener("click", () => showCrop([item.card_id]).catch((error) => showToast(error.message)));
  split.addEventListener("click", () => splitCard(item).catch((error) => showToast(error.message)));
  remove.addEventListener("click", () => deleteCard(item).catch((error) => showToast(error.message)));

  body.append(topLine, answerFields, captionLabel, notesLabel, actions);
  article.append(imagePane, body);
  return article;
}

async function loadCards() {
  const data = await fetchJson(`/api/cards?${activeFilters()}`);
  state.total = Number(data.total || 0);
  els.list.replaceChildren();
  if (!data.items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "이 조건에 맞는 카드가 없습니다.";
    els.list.appendChild(empty);
  } else {
    data.items.forEach((item) => els.list.appendChild(cardTemplate(item)));
  }

  const start = data.items.length ? state.offset + 1 : 0;
  const end = state.offset + data.items.length;
  els.pageLabel.textContent = `${start}-${end} / ${state.total}`;
  els.prev.disabled = state.offset === 0;
  els.next.disabled = state.offset + state.limit >= state.total;
  updateBulkButtons();
}

async function refresh() {
  try {
    await Promise.all([loadSummary(), loadCards()]);
  } catch (error) {
    els.list.replaceChildren();
    const message = document.createElement("div");
    message.className = "error";
    message.textContent = error.message;
    els.list.appendChild(message);
  }
}

async function saveCard(article) {
  const id = Number(article.dataset.id);
  const payload = {
    caption_text: article.querySelector(".caption").value,
    notes: article.querySelector(".notes").value,
  };
  if (article.dataset.answerEdited === "1") {
    payload.answer_title = article.querySelector(".answer-title-input").value;
    payload.answer_detail = article.querySelector(".answer-detail-input").value;
  }
  await fetchJson(`/api/cards/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  showToast(`#${id} 저장됨`);
  await refresh();
}

async function toggleFavorite(item) {
  await fetchJson("/api/study/favorite", {
    method: "POST",
    body: JSON.stringify({
      card_id: item.card_id,
      favorite: !item.is_favorite,
    }),
  });
  showToast(item.is_favorite ? `즐겨찾기 해제 #${item.card_id}` : `즐겨찾기 등록 #${item.card_id}`);
  await refresh();
}

async function togglePastExam(item) {
  await fetchJson("/api/study/past-exam", {
    method: "POST",
    body: JSON.stringify({
      card_id: item.card_id,
      past_exam: !item.is_past_exam,
    }),
  });
  showToast(item.is_past_exam ? `기출 해제 #${item.card_id}` : `기출문제 등록 #${item.card_id}`);
  await refresh();
}

function filterSameFigure(item) {
  if (!item.figure_key) {
    showToast("그림 번호를 찾을 수 없습니다.");
    return;
  }
  els.figure.value = item.figure_key;
  applyFilterInputs();
  refresh();
}

async function showCrop(ids) {
  if (!ids.length) {
    showToast("카드를 선택하세요.");
    return null;
  }
  const data = await fetchJson(`/api/cards/pdf-crop?card_ids=${ids.join(",")}`);
  els.cropPreview.replaceChildren();
  const image = document.createElement("img");
  image.src = data.image_url;
  image.alt = `PDF crop page ${data.page_number}`;
  const label = document.createElement("p");
  label.textContent = `p.${data.page_number} | ${ids.map((id) => `#${id}`).join(", ")}`;
  els.cropPreview.append(image, label);
  return data;
}

async function mergeSelectedCards() {
  const ids = Array.from(state.selected);
  if (ids.length < 2) {
    showToast("병합할 카드를 2개 이상 선택하세요.");
    return;
  }
  await showCrop(ids);
  if (!window.confirm("PDF crop을 확인한 뒤 선택한 카드를 병합할까요?")) return;
  const keepId = Math.min(...ids);
  await fetchJson("/api/cards/merge", {
    method: "POST",
    body: JSON.stringify({
      card_ids: ids,
      keep_card_id: keepId,
    }),
  });
  state.selected.clear();
  showToast(`병합 완료 #${keepId}`);
  await refresh();
}

async function splitCard(item) {
  if (!window.confirm(`#${item.card_id} 카드를 이미지별로 다시 분리할까요?`)) return;
  const data = await fetchJson(`/api/cards/${item.card_id}/split`, { method: "POST" });
  showToast(`분리 완료: ${data.card_ids.map((id) => `#${id}`).join(", ")}`);
  await refresh();
}

async function deleteCard(item) {
  if (!window.confirm(`#${item.card_id} 카드를 삭제할까요? 원본 추출 이미지는 보존됩니다.`)) return;
  await fetchJson(`/api/cards/${item.card_id}`, { method: "DELETE" });
  state.selected.delete(Number(item.card_id));
  showToast(`#${item.card_id} 삭제됨`);
  await refresh();
}

function updateBulkButtons() {
  const count = state.selected.size;
  els.mergeSelected.disabled = count < 2;
  els.cropSelected.disabled = count < 1;
  els.viewTitle.textContent = count ? `카드 관리 (${count} selected)` : "카드 관리";
}

els.applyFilters.addEventListener("click", () => {
  applyFilterInputs();
  refresh();
});

[els.query, els.chapter, els.page, els.figure].forEach((input) => {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      applyFilterInputs();
      refresh();
    }
  });
});

[els.pastExamOnly, els.multiOnly].forEach((input) => {
  input.addEventListener("change", () => {
    applyFilterInputs();
    refresh();
  });
});

els.pageSize.addEventListener("change", () => {
  state.limit = Number(els.pageSize.value);
  state.offset = 0;
  refresh();
});

els.refresh.addEventListener("click", () => refresh());
els.mergeSelected.addEventListener("click", () => mergeSelectedCards().catch((error) => showToast(error.message)));
els.cropSelected.addEventListener("click", () => showCrop(Array.from(state.selected)).catch((error) => showToast(error.message)));

els.prev.addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  refresh();
});

els.next.addEventListener("click", () => {
  state.offset += state.limit;
  refresh();
});

updateBulkButtons();
refresh();
