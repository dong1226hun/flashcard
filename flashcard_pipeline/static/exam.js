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
  sessionId: null,
  cards: [],
  index: 0,
  flipped: false,
  source: "all",
  chapter: null,
  sections: null,
};

const els = {
  deckTabs: document.querySelectorAll(".deck-tab"),
  chapterPicker: document.querySelector(".chapter-picker"),
  chapterSelect: document.querySelector("#chapter-select"),
  newSession: document.querySelector("#new-session"),
  shuffleSession: document.querySelector("#shuffle-session"),
  favoriteCard: document.querySelector("#favorite-card"),
  correctCard: document.querySelector("#correct-card"),
  wrongCard: document.querySelector("#wrong-card"),
  emptyState: document.querySelector("#empty-state"),
  cardShell: document.querySelector("#card-shell"),
  cardNumber: document.querySelector("#card-number"),
  imageFrame: document.querySelector("#image-frame"),
  images: document.querySelector("#card-images"),
  answerFace: document.querySelector("#answer-face"),
  answerMeta: document.querySelector("#answer-meta"),
  answerTitle: document.querySelector("#answer-title"),
  answerDetail: document.querySelector("#answer-detail"),
  prev: document.querySelector("#prev-card"),
  next: document.querySelector("#next-card"),
  reveal: document.querySelector("#reveal-answer"),
  progressBar: document.querySelector("#progress-bar"),
  cardList: document.querySelector("#card-list"),
  sectionAll: document.querySelector("#section-all"),
  sectionFavorites: document.querySelector("#section-favorites"),
  sectionPastExams: document.querySelector("#section-past-exams"),
  sectionWrong: document.querySelector("#section-wrong"),
  toast: document.querySelector("#toast"),
};

const FIGURE_RE = /(?:그림|Fig\.?|Figure)\s*(\d+)\s*[-‐‑‒–—―－]\s*(\d+[A-Za-z]?)/i;
const FIGURE_PREFIX_RE = /(?:그림|Fig\.?|Figure)\s*\d+\s*[-‐‑‒–—―－]\s*\d+[A-Za-z]?\s*[.)]?\s*/i;
const PANEL_PREFIX_RE = /^[A-Z](?:\s*,\s*[A-Z])*\s*[,.]\s*/i;
const PANEL_RANGE_PREFIX_RE = /^[A-Z]\s*~\s*[A-Z]\s*,\s*/i;

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

function chapterLabel(chapter, title = "") {
  if (chapter === "Unknown") return "Unknown";
  return title ? `Ch. ${chapter} ${title}` : `Ch. ${chapter}`;
}

function currentCard() {
  return state.cards[state.index];
}

function captionBody(caption) {
  return String(caption || "")
    .replace(FIGURE_PREFIX_RE, "")
    .replace(/·/g, "ㆍ")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanTitlePrefix(value) {
  return String(value || "")
    .replace(PANEL_RANGE_PREFIX_RE, "")
    .replace(/^[A-Z]\s*~\s*[A-Z]\s*/i, "")
    .replace(PANEL_PREFIX_RE, "")
    .trim();
}

function isTitleCandidate(value) {
  const text = cleanTitlePrefix(value);
  if (!text || /^[A-Z]\s*~?$/i.test(text) || /^[A-Z]\b/i.test(text)) return false;
  if (text.length > 34) return false;
  return !/(관찰된다|관찰되며|보인다|나타난다|있다|없다|필요하다|경우|것이다|소견)$/.test(text);
}

function splitCaptionFallback(caption) {
  const body = captionBody(caption);
  if (!body) return { title: "", detail: "" };
  const dotIndex = body.indexOf(".");
  const first = dotIndex >= 0 ? body.slice(0, dotIndex).trim() : body;
  const rest = dotIndex >= 0 ? body.slice(dotIndex + 1).trim() : "";
  const inlinePanel = first.match(/^(.{2,24}?)\s+([A-Z])\s*,\s*(.+)$/i);
  if (inlinePanel && !PANEL_RANGE_PREFIX_RE.test(first) && isTitleCandidate(inlinePanel[1])) {
    return {
      title: cleanTitlePrefix(inlinePanel[1]),
      detail: [`${inlinePanel[2].toUpperCase()}, ${inlinePanel[3].trim()}`, rest].filter(Boolean).join(". "),
    };
  }
  const subject = first.match(/^(.{2,24}?)(?:에서|의)\s+/);
  if (subject && isTitleCandidate(subject[1])) {
    return { title: cleanTitlePrefix(subject[1]), detail: body };
  }
  if (dotIndex >= 0 && isTitleCandidate(first)) {
    return { title: cleanTitlePrefix(first), detail: rest };
  }
  return { title: "", detail: body };
}

function cardAnswer(card) {
  const fallback = splitCaptionFallback(card.caption_text);
  return {
    title: card.answer_title || fallback.title,
    detail: card.answer_detail || fallback.detail || card.caption_text || "",
  };
}

function figureLabel(caption) {
  const match = String(caption || "").match(FIGURE_RE);
  if (!match) return "";
  return `그림 ${match[1]}-${match[2]}.`;
}

function shortText(value) {
  const text = String(value || "No caption").replace(/\s+/g, " ").trim();
  return text.length > 42 ? `${text.slice(0, 42)}...` : text;
}

function navigatorTitle(card) {
  const answer = cardAnswer(card);
  const label = figureLabel(card.caption_text);
  const title = answer.title || shortText(captionBody(card.caption_text) || card.caption_text);
  return [label, title].filter(Boolean).join(" ");
}

async function loadSections() {
  const previousWrong = Number(state.sections?.wrong ?? els.sectionWrong.textContent ?? 0) || 0;
  state.sections = await fetchJson("/api/study/sections");
  state.sections.wrong = Number.isFinite(Number(state.sections.wrong))
    ? Number(state.sections.wrong)
    : previousWrong;
  els.sectionAll.textContent = state.sections.all;
  els.sectionFavorites.textContent = state.sections.favorites;
  els.sectionPastExams.textContent = state.sections.past_exams;
  els.sectionWrong.textContent = state.sections.wrong;
  els.chapterSelect.replaceChildren();

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "단원 선택";
  els.chapterSelect.appendChild(placeholder);

  for (const item of state.sections.chapters) {
    const option = document.createElement("option");
    option.value = item.chapter;
    option.textContent = item.chapter === "Unknown"
      ? `Unknown (${item.count})`
      : `${chapterLabel(item.chapter, item.title)} (${item.count})`;
    els.chapterSelect.appendChild(option);
  }

  if (!state.chapter && state.sections.chapters.length) {
    state.chapter = state.sections.chapters[0].chapter;
  }
  els.chapterSelect.value = state.chapter || "";
}

async function startSession() {
  const session = await fetchJson("/api/study/session", {
    method: "POST",
    body: JSON.stringify({
      count: "all",
      source: state.source,
      chapter: state.source === "chapter" ? state.chapter : null,
      ordered: true,
    }),
  });
  state.sessionId = session.session_id;
  state.cards = session.cards || [];
  if (state.source === "wrong") {
    state.cards = state.cards.filter((card) => card.last_review_result === "wrong");
  }
  state.index = 0;
  state.flipped = false;
  render();
}

function shuffleCurrentSession() {
  for (let i = state.cards.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [state.cards[i], state.cards[j]] = [state.cards[j], state.cards[i]];
  }
  state.index = 0;
  state.flipped = false;
  render();
}

function renderImages(card) {
  els.images.replaceChildren();
  const images = card.images && card.images.length
    ? card.images
    : [{ image_url: card.image_url, image_width: card.image_width, image_height: card.image_height }];
  els.images.classList.toggle("multi", images.length > 1);
  for (const imageItem of images) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.src = imageItem.image_url;
    image.alt = "Flashcard image";
    els.images.appendChild(image);
  }
}

function render() {
  const empty = state.cards.length === 0;
  els.emptyState.classList.toggle("hidden", !empty);
  els.cardShell.classList.toggle("hidden", empty);
  if (empty) {
    els.cardList.replaceChildren();
    renderProgress();
    renderDeckControls();
    return;
  }

  const card = currentCard();
  const answer = cardAnswer(card);
  const hasAnswerTitle = Boolean(answer.title);
  const answerDetail = answer.detail || "";
  const answerMeta = [figureLabel(card.caption_text), `p.${card.source_page}`].filter(Boolean).join(" | ");
  els.cardNumber.textContent = String(state.index + 1);
  renderImages(card);
  els.answerMeta.textContent = answerMeta;
  els.answerMeta.classList.toggle("hidden", !answerMeta);
  els.answerTitle.textContent = answer.title;
  els.answerTitle.classList.toggle("hidden", !hasAnswerTitle);
  els.answerDetail.textContent = answerDetail;
  els.answerDetail.classList.toggle("hidden", !answerDetail);
  els.answerFace.classList.toggle("no-title", !hasAnswerTitle);
  els.imageFrame.classList.toggle("is-answer", state.flipped);
  els.imageFrame.setAttribute("aria-label", state.flipped ? "문제 보기" : "정답 보기");
  els.answerFace.classList.toggle("show", state.flipped);
  els.favoriteCard.classList.toggle("is-favorite", card.is_favorite);
  els.favoriteCard.textContent = card.is_favorite ? "즐겨찾기 해제" : "즐겨찾기";
  els.reveal.innerHTML = state.flipped
    ? '문제 <span class="kbd">Space</span>'
    : '정답 <span class="kbd">Space</span>';
  renderProgress();
  renderList();
  renderDeckControls();
}

function renderDeckControls() {
  els.deckTabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.source === state.source);
  });
  els.chapterPicker.classList.toggle("active", state.source === "chapter");
  els.chapterSelect.value = state.chapter || "";
}

function renderProgress() {
  els.progressBar.style.width = state.cards.length
    ? `${Math.round(((state.index + 1) / state.cards.length) * 100)}%`
    : "0%";
}

function renderList() {
  els.cardList.replaceChildren();
  state.cards.forEach((card, index) => {
    const item = document.createElement("div");
    item.className = [
      "item",
      index === state.index ? "active" : "",
      card.last_review_result === "correct" ? "review-correct" : "",
      card.last_review_result === "wrong" ? "review-wrong" : "",
    ].filter(Boolean).join(" ");
    const title = document.createElement("div");
    title.className = "item-title";
    const main = document.createElement("span");
    main.className = "item-main";
    main.textContent = navigatorTitle(card);
    const page = document.createElement("span");
    page.className = "item-page";
    page.textContent = ` | p.${card.source_page}`;
    title.append(main, page);
    item.append(title);
    if (card.last_review_result === "correct" || card.last_review_result === "wrong") {
      const status = document.createElement("span");
      status.className = `item-status ${card.last_review_result}`;
      status.textContent = card.last_review_result === "correct" ? "맞춤" : "틀림";
      item.append(status);
    }
    item.addEventListener("click", () => {
      state.index = index;
      state.flipped = false;
      render();
    });
    els.cardList.appendChild(item);
  });
}

function toggleAnswer() {
  if (!state.cards.length) return;
  state.flipped = !state.flipped;
  render();
}

function move(delta) {
  if (!state.cards.length) return;
  state.index = (state.index + delta + state.cards.length) % state.cards.length;
  state.flipped = false;
  render();
}

async function toggleFavorite() {
  const card = currentCard();
  if (!card) return;
  const result = await fetchJson("/api/study/favorite", {
    method: "POST",
    body: JSON.stringify({
      card_id: card.card_id,
      favorite: !card.is_favorite,
    }),
  });
  card.is_favorite = result.is_favorite;
  await loadSections();
  showToast(card.is_favorite ? "즐겨찾기에 추가됨" : "즐겨찾기 해제됨");
  if (state.source === "favorites" && !card.is_favorite) {
    state.cards.splice(state.index, 1);
    if (state.index >= state.cards.length) state.index = Math.max(0, state.cards.length - 1);
  }
  render();
}

function updateWrongSectionCount(previousResult, nextResult) {
  const current = Number(state.sections?.wrong ?? els.sectionWrong.textContent ?? 0) || 0;
  let nextCount = current;
  if (previousResult !== "wrong" && nextResult === "wrong") {
    nextCount += 1;
  } else if (previousResult === "wrong" && nextResult !== "wrong") {
    nextCount = Math.max(0, nextCount - 1);
  }
  if (!state.sections) state.sections = {};
  state.sections.wrong = nextCount;
  els.sectionWrong.textContent = nextCount;
}

async function recordResult(result) {
  const card = currentCard();
  if (!card || !state.sessionId) return;
  const previousResult = card.last_review_result || (state.source === "wrong" ? "wrong" : "");
  await fetchJson("/api/study/review", {
    method: "POST",
    body: JSON.stringify({
      session_id: state.sessionId,
      card_id: card.card_id,
      result,
    }),
  });
  card.last_review_result = result;
  updateWrongSectionCount(previousResult, result);
  loadSections().catch(() => {});
  showToast(result === "wrong" ? "틀림으로 기록됨" : "맞춤으로 기록됨");
  render();
}

els.newSession.addEventListener("click", () => startSession().catch((error) => showToast(error.message)));
els.shuffleSession.addEventListener("click", shuffleCurrentSession);
els.favoriteCard.addEventListener("click", () => toggleFavorite().catch((error) => showToast(error.message)));
els.correctCard.addEventListener("click", () => recordResult("correct").catch((error) => showToast(error.message)));
els.wrongCard.addEventListener("click", () => recordResult("wrong").catch((error) => showToast(error.message)));
els.deckTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    state.source = tab.dataset.source || "all";
    startSession().catch((error) => showToast(error.message));
  });
});
els.chapterSelect.addEventListener("change", () => {
  state.source = "chapter";
  state.chapter = els.chapterSelect.value || state.chapter;
  startSession().catch((error) => showToast(error.message));
});
els.prev.addEventListener("click", () => move(-1));
els.next.addEventListener("click", () => move(1));
els.reveal.addEventListener("click", toggleAnswer);
els.imageFrame.addEventListener("click", toggleAnswer);
els.imageFrame.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    toggleAnswer();
  }
});
document.addEventListener("keydown", (event) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  if (event.key === " ") {
    event.preventDefault();
    toggleAnswer();
  }
  if (event.key === "ArrowRight") move(1);
  if (event.key === "ArrowLeft") move(-1);
});

loadSections()
  .then(() => startSession())
  .catch((error) => showToast(error.message));
