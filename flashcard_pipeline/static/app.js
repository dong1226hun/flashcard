import("./theme.js").then(({ initThemeToggle }) => initThemeToggle());

const state = {
  limit: 24,
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
  pageNumbers: document.querySelector("#page-numbers"),
  prev: document.querySelector("#prev"),
  next: document.querySelector("#next"),
  refresh: document.querySelector("#refresh"),
  exportStatic: document.querySelector("#export-static"),
  pageSize: document.querySelector("#page-size"),
  mergeSelected: document.querySelector("#merge-selected"),
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
  if (!response.ok) throw new Error(data.error || "요청에 실패했습니다");
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

function setDraftToggle(buttonNode, active, activeText, inactiveText) {
  buttonNode.dataset.active = String(Boolean(active));
  buttonNode.className = active ? "exam active" : "secondary";
  buttonNode.textContent = active ? activeText : inactiveText;
}

function badge(text, className = "") {
  const node = document.createElement("span");
  node.className = `badge${className ? ` ${className}` : ""}`;
  node.textContent = text;
  return node;
}

function labelWithControl(text, control, options = {}) {
  const label = document.createElement("label");
  label.className = `field${options.className ? ` ${options.className}` : ""}`;
  if (options.types) label.dataset.visibleTypes = options.types.join(" ");
  label.textContent = text;
  label.appendChild(control);
  return label;
}

function syncTypeFields(article) {
  const select = article.querySelector(".card-type-select");
  const type = select?.value || "image";
  article.dataset.cardType = type;

  article.querySelectorAll("[data-visible-types]").forEach((node) => {
    const visibleTypes = (node.dataset.visibleTypes || "").split(" ");
    node.classList.toggle("is-hidden-by-type", !visibleTypes.includes(type));
  });

  const typeBadge = article.querySelector(".card-type-badge");
  if (typeBadge) typeBadge.textContent = cardTypeLabel(type);
}

function input(value = "", className = "") {
  const node = document.createElement("input");
  node.className = className;
  node.value = value;
  return node;
}

function textarea(value = "", className = "", rows = 3) {
  const node = document.createElement("textarea");
  node.className = className;
  node.rows = rows;
  node.value = value;
  return node;
}

function figureLabel(item) {
  return item.source_label || item.meta?.sourceLabel || "출처 없음";
}

function cardTypeLabel(type) {
  if (type === "multiple_choice") return "객관식";
  if (type === "short_answer") return "주관식";
  return "이미지";
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
  setText(els.documentCount, `${summary.available_cards}장`);
  setText(els.metrics.cards, summary.available_cards);
  setText(els.metrics.favorites, summary.favorite_cards);
  setText(els.metrics.pastExams, summary.past_exam_cards);
  setText(els.metrics.multi, multi.total);
}

function mediaItems(item) {
  return item.media && item.media.length ? item.media : item.images || [];
}

function setSelectedImage(article, imageId) {
  const selectedId = imageId ? String(imageId) : "";
  article.dataset.selectedImageId = selectedId;
  let selectedLabel = "";
  article.querySelectorAll(".image-select").forEach((node) => {
    const selected = node.dataset.imageId === selectedId;
    node.classList.toggle("is-selected", selected);
    node.setAttribute("aria-pressed", String(selected));
    const checkbox = node.querySelector(".image-select-checkbox");
    if (checkbox) checkbox.checked = selected;
    if (selected) selectedLabel = node.dataset.imageLabel || "";
  });
  const status = article.querySelector(".selected-image-status");
  if (status) status.textContent = selectedLabel || "선택된 그림 없음";
  const remove = article.querySelector(".remove-image-button");
  if (remove) remove.disabled = !selectedId;
  const confirmRemove = article.querySelector(".confirm-image-delete");
  if (confirmRemove) {
    confirmRemove.classList.add("hidden");
    confirmRemove.disabled = !selectedId;
  }
}

function renderImages(item, wrap, options = {}) {
  const media = mediaItems(item);
  wrap.classList.toggle("multi", media.length > 1);
  for (const mediaItem of media) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.src = mediaItem.src || mediaItem.image_url;
    image.alt = mediaItem.alt || `카드 이미지 ${item.source_page ? `${item.source_page}쪽` : ""}`;
    if (!options.selectable) {
      wrap.appendChild(image);
      continue;
    }
    const imageId = String(mediaItem.image_id || "");
    const imageButton = document.createElement("div");
    imageButton.className = "image-select";
    imageButton.dataset.imageId = imageId;
    imageButton.dataset.imageLabel = `선택: ${mediaItem.page_image_index ? `그림 ${mediaItem.page_image_index}` : `이미지 ${imageId}`}`;
    imageButton.tabIndex = 0;
    imageButton.setAttribute("role", "button");
    imageButton.setAttribute("aria-label", imageButton.dataset.imageLabel);
    imageButton.setAttribute("aria-pressed", "false");
    const selector = document.createElement("input");
    selector.type = "checkbox";
    selector.className = "image-select-checkbox";
    selector.setAttribute("aria-label", `${imageButton.dataset.imageLabel} 선택`);
    selector.addEventListener("click", (event) => event.stopPropagation());
    selector.addEventListener("change", () => {
      setSelectedImage(options.article, selector.checked ? imageId : "");
    });
    imageButton.append(image, selector);
    imageButton.addEventListener("click", () => setSelectedImage(options.article, imageId));
    imageButton.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setSelectedImage(options.article, imageId);
      }
    });
    wrap.appendChild(imageButton);
  }
}

function parseChoices(value) {
  const trimmed = value.trim();
  if (!trimmed) return [];
  const parsed = JSON.parse(trimmed);
  if (!Array.isArray(parsed)) throw new Error("선택지는 JSON 배열이어야 합니다");
  return parsed;
}

function choiceId(choice) {
  return choice && choice.id !== undefined && choice.id !== null ? String(choice.id).trim() : "";
}

function choiceText(choice, index) {
  if (choice && choice.text !== undefined && choice.text !== null) return String(choice.text);
  if (choice && choice.label !== undefined && choice.label !== null) return String(choice.label);
  return `선택지 ${index + 1}`;
}

function selectedChoiceIds(article) {
  return Array.from(article.querySelectorAll(".correct-choice-option input:checked"))
    .map((input) => input.value)
    .filter(Boolean);
}

function correctChoiceField(choicesControl, initialChoiceIds) {
  const field = document.createElement("div");
  field.className = "field correct-choice-field field-full";
  field.dataset.visibleTypes = "multiple_choice";

  const title = document.createElement("span");
  title.className = "field-label";
  title.textContent = "정답 선택";
  const options = document.createElement("div");
  options.className = "correct-choice-options";
  field.append(title, options);

  let selected = new Set((initialChoiceIds || []).map(String));
  const syncFromChecked = () => {
    selected = new Set(Array.from(options.querySelectorAll("input:checked")).map((input) => input.value));
  };
  const render = () => {
    if (options.childElementCount) syncFromChecked();
    options.replaceChildren();
    let choices;
    try {
      choices = parseChoices(choicesControl.value);
    } catch (error) {
      const message = document.createElement("div");
      message.className = "choice-helper";
      message.textContent = "선택지 JSON을 먼저 올바르게 입력하세요";
      options.appendChild(message);
      return;
    }
    if (!choices.length) {
      const message = document.createElement("div");
      message.className = "choice-helper";
      message.textContent = "선택지가 없습니다";
      options.appendChild(message);
      return;
    }
    choices.forEach((choice, index) => {
      const id = choiceId(choice);
      const label = document.createElement("label");
      label.className = "correct-choice-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = id;
      checkbox.checked = selected.has(id);
      checkbox.disabled = !id;
      checkbox.addEventListener("change", syncFromChecked);
      const text = document.createElement("span");
      text.textContent = id ? choiceText(choice, index) : `${choiceText(choice, index)} (id 없음)`;
      label.append(checkbox, text);
      options.appendChild(label);
    });
  };
  choicesControl.addEventListener("input", render);
  render();
  return field;
}

function compactText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function itemType(item) {
  return item.card_type || item.type || "image";
}

function itemPrompt(item) {
  return compactText(item.prompt_text || item.prompt?.text);
}

function itemAnswer(item) {
  return compactText(item.answer_text || item.answer?.text);
}

function tileTitle(item) {
  if (itemType(item) === "image") {
    return itemAnswer(item) || itemPrompt(item) || "제목 없음";
  }
  return itemPrompt(item) || "문제 없음";
}

function tileStatusBadges(item) {
  const statuses = [];
  if (item.last_review_result === "wrong") statuses.push(["틀림", "wrong"]);
  if (item.is_favorite) statuses.push(["즐겨찾기", "favorite"]);
  if (item.is_past_exam) statuses.push(["기출", "past-exam"]);
  return statuses;
}

function closeEditor() {
  const overlay = document.querySelector("#editor-overlay");
  if (!overlay) return;
  overlay.classList.add("hidden");
  document.body.classList.remove("modal-open");
  const body = overlay.querySelector(".editor-dialog-body");
  if (body) body.replaceChildren();
}

function ensureEditorOverlay() {
  let overlay = document.querySelector("#editor-overlay");
  if (overlay) return overlay;

  overlay = document.createElement("div");
  overlay.id = "editor-overlay";
  overlay.className = "editor-overlay hidden";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");

  const backdrop = document.createElement("button");
  backdrop.type = "button";
  backdrop.className = "editor-backdrop";
  backdrop.setAttribute("aria-label", "편집창 닫기");
  backdrop.addEventListener("click", closeEditor);

  const dialog = document.createElement("div");
  dialog.className = "editor-dialog";

  const header = document.createElement("div");
  header.className = "editor-dialog-header";
  const title = document.createElement("h3");
  title.textContent = "카드 수정";
  const close = button("닫기", "secondary editor-close");
  close.addEventListener("click", closeEditor);
  header.append(title, close);

  const body = document.createElement("div");
  body.className = "editor-dialog-body";
  dialog.append(header, body);
  overlay.append(backdrop, dialog);
  document.body.appendChild(overlay);
  return overlay;
}

function renderEditorCard(item) {
  const overlay = ensureEditorOverlay();
  const title = overlay.querySelector(".editor-dialog-header h3");
  if (title) title.textContent = `#${item.card_id} 카드 수정`;
  const body = overlay.querySelector(".editor-dialog-body");
  body.replaceChildren(cardTemplate(item));
  return overlay;
}

function openEditor(item) {
  const overlay = renderEditorCard(item);
  overlay.classList.remove("hidden");
  document.body.classList.add("modal-open");
  const firstControl = overlay.querySelector(".card-type-select");
  if (firstControl) firstControl.focus();
}

function cardTile(item) {
  const article = document.createElement("article");
  const type = itemType(item);
  const media = mediaItems(item);
  article.className = `card-tile ${type === "image" && media.length ? "has-thumb" : "text-only"}`;
  article.dataset.id = item.card_id;
  article.dataset.cardType = type;
  article.tabIndex = 0;
  article.setAttribute("role", "button");
  article.setAttribute("aria-label", `#${item.card_id} 카드 수정`);

  const selector = document.createElement("label");
  selector.className = "tile-select";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.selected.has(Number(item.card_id));
  checkbox.addEventListener("click", (event) => event.stopPropagation());
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.selected.add(Number(item.card_id));
    else state.selected.delete(Number(item.card_id));
    article.classList.toggle("is-selected", checkbox.checked);
    updateBulkButtons();
  });
  checkbox.setAttribute("aria-label", `#${item.card_id} 선택`);
  selector.addEventListener("click", (event) => event.stopPropagation());
  selector.append(checkbox);

  const body = document.createElement("div");
  body.className = "tile-body";

  const meta = document.createElement("div");
  meta.className = "tile-meta";
  const number = document.createElement("span");
  number.className = "tile-number";
  number.textContent = `#${item.card_id}`;
  const status = document.createElement("div");
  status.className = "tile-status";
  for (const [text, className] of tileStatusBadges(item)) {
    status.appendChild(badge(text, className));
  }
  meta.append(selector, number, status);
  body.appendChild(meta);

  if (type === "image" && media.length) {
    const thumb = document.createElement("div");
    thumb.className = "tile-thumb";
    const image = document.createElement("img");
    image.loading = "lazy";
    image.src = media[0].src || media[0].image_url;
    image.alt = media[0].alt || "카드 이미지";
    thumb.appendChild(image);
    body.appendChild(thumb);
  }

  const textRow = document.createElement("div");
  textRow.className = "tile-text-row";
  const title = document.createElement("div");
  title.className = "item-title tile-title";
  const main = document.createElement("span");
  main.className = "item-main";
  main.textContent = tileTitle(item);
  title.appendChild(main);

  const source = document.createElement("span");
  source.className = "item-page tile-source";
  source.textContent = figureLabel(item);
  textRow.append(title, source);
  body.appendChild(textRow);

  article.classList.toggle("is-selected", checkbox.checked);
  article.appendChild(body);
  article.addEventListener("click", () => openEditor(item));
  article.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openEditor(item);
    }
  });
  return article;
}

function pageButton(page, currentPage) {
  const node = button(String(page), "secondary page-number");
  node.classList.toggle("is-current", page === currentPage);
  node.disabled = page === currentPage;
  node.setAttribute("aria-label", `${page}페이지로 이동`);
  if (page === currentPage) node.setAttribute("aria-current", "page");
  node.addEventListener("click", () => {
    state.offset = (page - 1) * state.limit;
    refresh();
  });
  return node;
}

function renderPageNumbers() {
  if (!els.pageNumbers) return;
  els.pageNumbers.replaceChildren();
  const pageCount = Math.ceil(state.total / state.limit);
  if (pageCount <= 1) return;

  const currentPage = Math.floor(state.offset / state.limit) + 1;
  const pages = new Set([1, pageCount]);
  const addRange = (start, end) => {
    for (let page = Math.max(1, start); page <= Math.min(pageCount, end); page += 1) {
      pages.add(page);
    }
  };

  if (pageCount <= 7) {
    addRange(1, pageCount);
  } else if (currentPage <= 4) {
    addRange(1, 5);
  } else if (currentPage >= pageCount - 3) {
    addRange(pageCount - 4, pageCount);
  } else {
    addRange(currentPage - 1, currentPage + 1);
  }

  let previous = 0;
  for (const page of Array.from(pages).sort((a, b) => a - b)) {
    if (previous && page - previous > 1) {
      const gap = document.createElement("span");
      gap.className = "page-gap";
      gap.textContent = "...";
      els.pageNumbers.appendChild(gap);
    }
    els.pageNumbers.appendChild(pageButton(page, currentPage));
    previous = page;
  }
}

function cardTemplate(item) {
  const article = document.createElement("article");
  article.className = "card-row";
  article.dataset.id = item.card_id;
  article.dataset.cardType = item.card_type || item.type || "image";
  const media = mediaItems(item);
  article.dataset.selectedImageId = "";

  const imagePane = document.createElement("div");
  imagePane.className = "image-pane";
  const imageWrap = document.createElement("div");
  imageWrap.className = "image-wrap";
  renderImages(item, imageWrap, { selectable: true, article });
  const imageActions = document.createElement("div");
  imageActions.className = "image-actions";
  const selectedImageStatus = document.createElement("span");
  selectedImageStatus.className = "selected-image-status";
  selectedImageStatus.textContent = "선택된 그림 없음";
  const addMenu = document.createElement("div");
  addMenu.className = "image-add-menu";
  const addImage = button("그림 추가", "secondary image-add-trigger");
  const addPopover = document.createElement("div");
  addPopover.className = "image-add-popover";
  const upload = document.createElement("label");
  upload.className = "image-menu-item upload-menu-item";
  upload.textContent = "로컬에서 업로드";
  const uploadInput = document.createElement("input");
  uploadInput.type = "file";
  uploadInput.accept = "image/png,image/jpeg,image/webp";
  uploadInput.addEventListener("change", () => {
    uploadImageFile(article, uploadInput.files?.[0]).catch((error) => showToast(error.message));
  });
  upload.appendChild(uploadInput);
  const addExisting = button("기존 사진에서 추가", "image-menu-item");
  addPopover.append(upload, addExisting);
  addMenu.append(addImage, addPopover);
  const removeImage = button("그림 삭제", "danger remove-image-button");
  const confirmRemoveImage = button("삭제 확인", "danger confirm-image-delete hidden");
  const imagePicker = document.createElement("div");
  imagePicker.className = "image-picker hidden";
  imageActions.append(selectedImageStatus, addMenu, removeImage, confirmRemoveImage);
  imagePane.append(imageWrap, imageActions, imagePicker);

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
  title.textContent = item.prompt_text || item.prompt?.text || figureLabel(item);
  const subtitle = document.createElement("span");
  subtitle.textContent = item.answer_text || item.answer?.text || "정답 없음";
  heading.append(title, subtitle);
  topLine.append(selector, heading);

  const typeSelect = document.createElement("select");
  typeSelect.className = "card-type-select";
  for (const type of ["image", "multiple_choice", "short_answer"]) {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = cardTypeLabel(type);
    option.selected = type === (item.card_type || item.type);
    typeSelect.appendChild(option);
  }

  const typeControl = document.createElement("div");
  typeControl.className = "type-control";
  typeControl.appendChild(labelWithControl("카드 유형", typeSelect, { className: "type-field" }));

  const prompt = textarea(item.prompt_text || item.prompt?.text || "", "prompt-input", 2);
  const answer = textarea(item.answer_text || item.answer?.text || "", "answer-text-input", 3);
  const explanation = textarea(item.answer_explanation || item.answer?.explanation || "", "answer-explanation-input", 3);
  const choices = textarea(item.choices_json || JSON.stringify(item.choices || [], null, 2), "choices-input", 5);
  const correctChoices = correctChoiceField(choices, item.answer?.choiceIds || []);
  const sourceLabel = input(item.source_label || item.meta?.sourceLabel || "", "source-label-input");
  const chapter = input(item.chapter || item.meta?.chapter || "", "chapter-input");
  const sortOrder = input(String(item.sortOrder || 0), "sort-order-input");
  sortOrder.inputMode = "numeric";
  const caption = textarea(item.caption_text || item.source?.captionText || "", "caption", 3);
  const notes = textarea(item.notes || item.source?.notes || "", "notes", 3);

  const fields = document.createElement("div");
  fields.className = "answer-fields edit-form";
  fields.append(
    labelWithControl("문제", prompt, {
      className: "prompt-field field-full",
      types: ["multiple_choice", "short_answer"],
    }),
    labelWithControl("선택지 JSON", choices, {
      className: "choices-field field-full",
      types: ["multiple_choice"],
    }),
    correctChoices,
    labelWithControl("정답", answer, { className: "answer-field field-full" }),
    labelWithControl("해설", explanation, { className: "explanation-field field-full" }),
    labelWithControl("출처 라벨", sourceLabel, { className: "source-label-field" }),
    labelWithControl("단원", chapter, { className: "chapter-field" }),
    labelWithControl("원본 캡션", caption, {
      className: "caption-field field-full",
      types: ["image"],
    }),
  );

  const advanced = document.createElement("details");
  advanced.className = "advanced-fields";
  const advancedSummary = document.createElement("summary");
  advancedSummary.textContent = "고급사항";
  const advancedBody = document.createElement("div");
  advancedBody.className = "answer-fields edit-form advanced-grid";
  advancedBody.append(
    labelWithControl("정렬 순서", sortOrder, { className: "sort-order-field" }),
    labelWithControl("메모", notes, { className: "notes-field field-full" }),
  );
  advanced.append(advancedSummary, advancedBody);
  typeSelect.addEventListener("change", () => syncTypeFields(article));

  const actions = document.createElement("div");
  actions.className = "actions";
  const save = button("저장", "primary");
  const favorite = button(item.is_favorite ? "즐겨찾기 해제" : "즐겨찾기", item.is_favorite ? "exam active" : "secondary");
  const pastExam = button(item.is_past_exam ? "기출 해제" : "기출", item.is_past_exam ? "exam active" : "secondary");
  const sameFigure = button("같은 그림", "secondary");
  const split = button("분리", "warning");
  const remove = button("삭제", "danger delete-trigger");
  const confirmRemove = button("삭제 확인", "danger confirm-delete hidden");
  favorite.dataset.reviewToggle = "favorite";
  pastExam.dataset.reviewToggle = "past-exam";
  setDraftToggle(favorite, item.is_favorite, "즐겨찾기 해제", "즐겨찾기");
  setDraftToggle(pastExam, item.is_past_exam, "기출 해제", "기출");
  split.disabled = Number(item.image_count || 0) <= 1;
  actions.append(save, favorite, pastExam, sameFigure, split, remove, confirmRemove);
  const hideDeleteConfirmation = () => confirmRemove.classList.add("hidden");

  save.addEventListener("click", () => {
    hideDeleteConfirmation();
    saveCard(article).catch((error) => showToast(error.message));
  });
  favorite.addEventListener("click", () => {
    hideDeleteConfirmation();
    setDraftToggle(favorite, favorite.dataset.active !== "true", "즐겨찾기 해제", "즐겨찾기");
  });
  pastExam.addEventListener("click", () => {
    hideDeleteConfirmation();
    setDraftToggle(pastExam, pastExam.dataset.active !== "true", "기출 해제", "기출");
  });
  sameFigure.addEventListener("click", () => {
    hideDeleteConfirmation();
    filterSameFigure(item);
  });
  split.addEventListener("click", () => {
    hideDeleteConfirmation();
    splitCard(item).catch((error) => showToast(error.message));
  });
  remove.addEventListener("click", () => {
    confirmRemove.classList.remove("hidden");
    confirmRemove.focus();
  });
  confirmRemove.addEventListener("click", () => deleteCard(item).catch((error) => showToast(error.message)));
  addExisting.addEventListener("click", () => toggleImagePicker(article, imagePicker).catch((error) => showToast(error.message)));
  removeImage.addEventListener("click", () => {
    confirmRemoveImage.classList.remove("hidden");
    confirmRemoveImage.focus();
  });
  confirmRemoveImage.addEventListener("click", () => removeSelectedImage(article).catch((error) => showToast(error.message)));

  body.append(actions, typeControl, fields, advanced);
  article.append(imagePane, body);
  syncTypeFields(article);
  setSelectedImage(article, article.dataset.selectedImageId);
  return article;
}

async function loadCards() {
  const data = await fetchJson(`/api/cards?${activeFilters()}`);
  state.total = Number(data.total || 0);
  els.list.replaceChildren();
  if (!data.items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "현재 필터에 맞는 카드가 없습니다.";
    els.list.appendChild(empty);
  } else {
    data.items.forEach((item) => els.list.appendChild(cardTile(item)));
  }

  const start = data.items.length ? state.offset + 1 : 0;
  const end = state.offset + data.items.length;
  els.pageLabel.textContent = `${start}-${end} / ${state.total}`;
  els.prev.disabled = state.offset === 0;
  els.next.disabled = state.offset + state.limit >= state.total;
  renderPageNumbers();
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

async function exportStatic() {
  if (!els.exportStatic) return;
  const originalText = els.exportStatic.textContent;
  els.exportStatic.disabled = true;
  els.exportStatic.textContent = "저장 중...";
  try {
    const result = await fetchJson("/api/static-export", { method: "POST" });
    showToast(`static 저장 완료: ${result.cards}장`);
  } finally {
    els.exportStatic.disabled = false;
    els.exportStatic.textContent = originalText;
  }
}

function pickerImageLabel(image) {
  const page = image.page_number ? `${image.page_number}쪽` : "쪽 없음";
  const index = image.page_image_index ? `그림 ${image.page_image_index}` : `이미지 ${image.image_id}`;
  return `${page} · ${index}`;
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    });
    reader.addEventListener("error", () => reject(new Error("파일을 읽지 못했습니다")));
    reader.readAsDataURL(file);
  });
}

async function refreshEditorWithCard(card, message) {
  renderEditorCard(card);
  showToast(message);
  await refresh();
}

async function addExistingImage(article, imageId) {
  const cardId = Number(article.dataset.id);
  const card = await fetchJson(`/api/cards/${cardId}/images`, {
    method: "POST",
    body: JSON.stringify({ image_id: Number(imageId) }),
  });
  await refreshEditorWithCard(card, `#${cardId}에 그림을 추가했습니다`);
}

async function uploadImageFile(article, file) {
  if (!file) return;
  const cardId = Number(article.dataset.id);
  const dataBase64 = await fileAsBase64(file);
  const card = await fetchJson(`/api/cards/${cardId}/images/upload`, {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type,
      data_base64: dataBase64,
    }),
  });
  await refreshEditorWithCard(card, `#${cardId}에 그림을 업로드했습니다`);
}

function renderImagePicker(article, panel, images) {
  panel.replaceChildren();

  const title = document.createElement("div");
  title.className = "image-picker-title";
  title.textContent = "기존 그림 선택";

  const grid = document.createElement("div");
  grid.className = "image-picker-grid";
  if (!images.length) {
    const empty = document.createElement("div");
    empty.className = "choice-helper";
    empty.textContent = "추가할 수 있는 그림이 없습니다";
    grid.appendChild(empty);
  }
  for (const image of images) {
    const option = button("", "image-picker-option");
    option.disabled = Boolean(image.is_attached);
    option.title = image.is_attached ? "이미 현재 카드에 있습니다" : pickerImageLabel(image);
    const thumb = document.createElement("img");
    thumb.loading = "lazy";
    thumb.src = image.src || image.image_url;
    thumb.alt = pickerImageLabel(image);
    const text = document.createElement("span");
    text.textContent = image.is_attached ? `${pickerImageLabel(image)} · 추가됨` : pickerImageLabel(image);
    option.append(thumb, text);
    option.addEventListener("click", () => addExistingImage(article, image.image_id).catch((error) => showToast(error.message)));
    grid.appendChild(option);
  }

  panel.append(title, grid);
}

async function toggleImagePicker(article, panel) {
  if (!panel.classList.contains("hidden")) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  panel.textContent = "그림 목록을 불러오는 중...";
  const cardId = Number(article.dataset.id);
  const data = await fetchJson(`/api/images?card_id=${cardId}`);
  renderImagePicker(article, panel, data.items || []);
}

async function removeSelectedImage(article) {
  const cardId = Number(article.dataset.id);
  const imageId = article.dataset.selectedImageId;
  if (!imageId) {
    showToast("삭제할 그림을 먼저 선택하세요");
    return;
  }
  const card = await fetchJson(`/api/cards/${cardId}/images/${imageId}`, { method: "DELETE" });
  await refreshEditorWithCard(card, `#${cardId}에서 그림을 제거했습니다`);
}

async function saveCard(article) {
  const id = Number(article.dataset.id);
  const cardType = article.querySelector(".card-type-select").value;
  const favoriteToggle = article.querySelector('[data-review-toggle="favorite"]');
  const pastExamToggle = article.querySelector('[data-review-toggle="past-exam"]');
  const payload = {
    card_type: cardType,
    prompt_text: cardType === "image" ? "" : article.querySelector(".prompt-input").value,
    answer_text: article.querySelector(".answer-text-input").value,
    answer_explanation: article.querySelector(".answer-explanation-input").value,
    choices: cardType === "multiple_choice" ? parseChoices(article.querySelector(".choices-input").value) : [],
    answer_choice_ids: cardType === "multiple_choice" ? selectedChoiceIds(article) : [],
    source_label: article.querySelector(".source-label-input").value,
    chapter: article.querySelector(".chapter-input").value,
    sort_order: Number(article.querySelector(".sort-order-input").value || 0),
    caption_text: article.querySelector(".caption").value,
    notes: article.querySelector(".notes").value,
  };
  await fetchJson(`/api/cards/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  await Promise.all([
    fetchJson("/api/study/favorite", {
      method: "POST",
      body: JSON.stringify({
        card_id: id,
        favorite: favoriteToggle?.dataset.active === "true",
      }),
    }),
    fetchJson("/api/study/past-exam", {
      method: "POST",
      body: JSON.stringify({
        card_id: id,
        past_exam: pastExamToggle?.dataset.active === "true",
      }),
    }),
  ]);
  showToast(`#${id} 저장했습니다`);
  closeEditor();
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
  showToast(item.is_favorite ? `#${item.card_id} 즐겨찾기를 해제했습니다` : `#${item.card_id} 즐겨찾기에 추가했습니다`);
  closeEditor();
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
  showToast(item.is_past_exam ? `#${item.card_id} 기출 표시를 해제했습니다` : `#${item.card_id} 기출로 표시했습니다`);
  closeEditor();
  await refresh();
}

function filterSameFigure(item) {
  const key = item.figure_key || figureKeyFromLabel(figureLabel(item));
  if (!key) {
    showToast("이 카드에는 출처 라벨이 없습니다");
    return;
  }
  els.figure.value = key;
  applyFilterInputs();
  closeEditor();
  refresh();
}

function figureKeyFromLabel(label) {
  return String(label || "").replace(/^Fig\.\s*/i, "").replace(/\.$/, "");
}

async function mergeSelectedCards() {
  const ids = Array.from(state.selected);
  if (ids.length < 2) {
    showToast("합치려면 카드를 두 개 이상 선택하세요");
    return;
  }
  if (!window.confirm("선택한 카드를 합칠까요?")) return;
  const keepId = Math.min(...ids);
  await fetchJson("/api/cards/merge", {
    method: "POST",
    body: JSON.stringify({
      card_ids: ids,
      keep_card_id: keepId,
    }),
  });
  state.selected.clear();
  showToast(`#${keepId}로 합쳤습니다`);
  await refresh();
}

async function splitCard(item) {
  if (!window.confirm(`#${item.card_id}를 이미지별 카드로 분리할까요?`)) return;
  const data = await fetchJson(`/api/cards/${item.card_id}/split`, { method: "POST" });
  showToast(`분리 완료: ${data.card_ids.map((id) => `#${id}`).join(", ")}`);
  closeEditor();
  await refresh();
}

async function deleteCard(item) {
  await fetchJson(`/api/cards/${item.card_id}`, { method: "DELETE" });
  state.selected.delete(Number(item.card_id));
  showToast(`#${item.card_id} 삭제했습니다`);
  closeEditor();
  await refresh();
}

function updateBulkButtons() {
  const count = state.selected.size;
  els.mergeSelected.disabled = count < 2;
  els.viewTitle.textContent = count ? `카드 관리 (${count}개 선택)` : "카드 관리";
}

els.applyFilters.addEventListener("click", () => {
  applyFilterInputs();
  refresh();
});

[els.query, els.chapter, els.page, els.figure].forEach((field) => {
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      applyFilterInputs();
      refresh();
    }
  });
});

[els.pastExamOnly, els.multiOnly].forEach((field) => {
  field.addEventListener("change", () => {
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
if (els.exportStatic) {
  els.exportStatic.addEventListener("click", () => exportStatic().catch((error) => showToast(error.message)));
}
els.mergeSelected.addEventListener("click", () => mergeSelectedCards().catch((error) => showToast(error.message)));

els.prev.addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  refresh();
});

els.next.addEventListener("click", () => {
  state.offset = Math.min(Math.max(0, state.total - 1), state.offset + state.limit);
  refresh();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeEditor();
});

updateBulkButtons();
refresh();
