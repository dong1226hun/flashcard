import { createApiProvider, createStaticProvider } from "./providers.js?v=6";
import { initThemeToggle } from "./theme.js?v=6";
import { navigatorTitle, renderAnswer, renderQuestion } from "./renderers.js?v=6";

initThemeToggle();

function currentModuleScript() {
  return document.currentScript
    || document.querySelector('script[src*="static/study/main.js"][data-provider]');
}

const script = currentModuleScript();
const providerMode = script?.dataset.provider === "static" ? "static" : "api";
const provider = providerMode === "static" ? createStaticProvider() : createApiProvider();
const TYPE_OPTIONS = [
  ["image", "이미지"],
  ["multiple_choice", "객관식"],
  ["short_answer", "주관식"],
];

const state = {
  sessionId: null,
  cards: [],
  index: 0,
  revealed: false,
  source: "all",
  chapter: null,
  cardType: "",
  query: "",
  sections: null,
  selectedChoiceIds: new Set(),
  shortAnswerText: "",
};

const els = {
  deckTabs: document.querySelectorAll(".deck-tab"),
  filterbar: document.querySelector(".study-filterbar"),
  query: document.querySelector("#study-query"),
  typeSelect: document.querySelector("#type-select"),
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
  questionFace: document.querySelector("#question-face"),
  questionType: document.querySelector("#question-type"),
  questionPrompt: document.querySelector("#question-prompt"),
  images: document.querySelector("#card-images"),
  choiceList: document.querySelector("#choice-list"),
  shortAnswer: document.querySelector("#short-answer-input"),
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

let toastTimer;
let filterTimer;

function showToast(message) {
  clearTimeout(toastTimer);
  els.toast.textContent = message;
  els.toast.classList.add("show");
  toastTimer = setTimeout(() => els.toast.classList.remove("show"), 2200);
}

function chapterLabel(chapter, title = "") {
  if (chapter === "Unknown") return "미분류";
  return title || `단원 ${chapter}`;
}

function typeCounts() {
  return new Map((state.sections?.types || []).map((item) => [item.type, Number(item.count) || 0]));
}

function renderTypeOptions() {
  const counts = typeCounts();
  const current = state.cardType || "";
  els.typeSelect.replaceChildren();

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "문제유형";
  els.typeSelect.appendChild(placeholder);

  for (const [type, label] of TYPE_OPTIONS) {
    const count = counts.get(type) || 0;
    const option = document.createElement("option");
    option.value = type;
    option.textContent = `${label} (${count})`;
    option.disabled = count === 0;
    els.typeSelect.appendChild(option);
  }

  if (current && !counts.get(current)) {
    state.cardType = "";
  }
  els.typeSelect.value = state.cardType || "";
}

function currentCard() {
  return state.cards[state.index];
}

function resetAnswerState() {
  state.revealed = false;
  state.selectedChoiceIds = new Set();
  state.shortAnswerText = "";
}

function updateCardReview(card, patch) {
  card.review = { ...card.review, ...patch };
  card.is_favorite = card.review.favorite;
  card.last_review_result = card.review.lastResult;
}

async function loadSections() {
  state.sections = await provider.loadSections();
  els.sectionAll.textContent = state.sections.all;
  els.sectionFavorites.textContent = state.sections.favorites;
  els.sectionPastExams.textContent = state.sections.past_exams;
  els.sectionWrong.textContent = state.sections.wrong;
  renderTypeOptions();
  els.chapterSelect.replaceChildren();

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "단원명";
  els.chapterSelect.appendChild(placeholder);

  for (const item of state.sections.chapters) {
    const option = document.createElement("option");
    option.value = item.chapter;
    option.textContent = item.chapter === "Unknown"
      ? `미분류 (${item.count})`
      : `${chapterLabel(item.chapter, item.title)} (${item.count})`;
    els.chapterSelect.appendChild(option);
  }

  els.chapterSelect.value = state.chapter || "";
}

async function startSession({ ordered = true } = {}) {
  const session = await provider.startSession({
    source: state.source,
    chapter: state.chapter || null,
    cardType: state.cardType || "",
    query: state.query.trim(),
    ordered,
  });
  state.sessionId = session.session_id;
  state.cards = session.cards || [];
  state.index = 0;
  resetAnswerState();
  render();
}

function shuffleCurrentSession() {
  for (let i = state.cards.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [state.cards[i], state.cards[j]] = [state.cards[j], state.cards[i]];
  }
  state.index = 0;
  resetAnswerState();
  render();
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
  els.cardNumber.textContent = String(state.index + 1);
  renderQuestion(card, els, state);
  renderAnswer(card, els);

  els.imageFrame.classList.toggle("is-answer", state.revealed);
  els.imageFrame.setAttribute("aria-label", state.revealed ? "문제 보기" : "정답 보기");
  els.questionFace.setAttribute("aria-hidden", String(state.revealed));
  els.answerFace.setAttribute("aria-hidden", String(!state.revealed));
  els.questionFace.toggleAttribute("inert", state.revealed);
  els.answerFace.toggleAttribute("inert", !state.revealed);

  els.favoriteCard.classList.toggle("is-favorite", card.review.favorite);
  els.favoriteCard.textContent = card.review.favorite ? "즐겨찾기 해제" : "즐겨찾기";
  els.reveal.innerHTML = state.revealed
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
  els.filterbar.classList.toggle(
    "active",
    Boolean(state.query.trim() || state.cardType || state.chapter),
  );
  els.query.value = state.query;
  els.typeSelect.value = state.cardType || "";
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
    const result = card.review.lastResult;
    item.className = [
      "item",
      index === state.index ? "active" : "",
      result === "correct" ? "review-correct" : "",
      result === "wrong" ? "review-wrong" : "",
    ].filter(Boolean).join(" ");

    const title = document.createElement("div");
    title.className = "item-title";
    const main = document.createElement("span");
    main.className = "item-main";
    main.textContent = navigatorTitle(card);
    const page = document.createElement("span");
    page.className = "item-page";
    page.textContent = card.meta.sourcePage ? ` | p.${card.meta.sourcePage}` : "";
    title.append(main, page);
    item.append(title);

    if (["correct", "wrong"].includes(result)) {
      const status = document.createElement("span");
      status.className = `item-status ${result}`;
      status.textContent = result === "correct" ? "맞음" : "틀림";
      item.append(status);
    }

    item.addEventListener("click", () => {
      state.index = index;
      resetAnswerState();
      render();
    });
    els.cardList.appendChild(item);
  });
}

function toggleAnswer() {
  if (!state.cards.length) return;
  state.revealed = !state.revealed;
  render();
}

function move(delta) {
  if (!state.cards.length) return;
  state.index = (state.index + delta + state.cards.length) % state.cards.length;
  resetAnswerState();
  render();
}

async function toggleFavorite() {
  const card = currentCard();
  if (!card) return;
  const nextFavorite = !card.review.favorite;
  await provider.setFavorite(card, nextFavorite);
  updateCardReview(card, { favorite: nextFavorite });
  await loadSections();
  showToast(nextFavorite ? "즐겨찾기에 추가했습니다" : "즐겨찾기에서 해제했습니다");
  if (state.source === "favorites" && !nextFavorite) {
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
  state.sections = { ...(state.sections || {}), wrong: nextCount };
  els.sectionWrong.textContent = nextCount;
}

async function recordResult(result) {
  const card = currentCard();
  if (!card || !state.sessionId) return;
  const previousResult = card.review.lastResult;
  await provider.recordResult(state.sessionId, card, result);
  updateCardReview(card, { lastResult: result });
  updateWrongSectionCount(previousResult, result);
  loadSections().catch(() => {});
  showToast(result === "correct" ? "맞음으로 기록했습니다" : "틀림으로 기록했습니다");
  render();
}

function isInteractiveClick(target) {
  return Boolean(target.closest("button, input, textarea, select, label"));
}

function queueFilteredSession() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    startSession({ ordered: true }).catch((error) => showToast(error.message));
  }, 240);
}

els.newSession.addEventListener("click", () => startSession({ ordered: true }).catch((error) => showToast(error.message)));
els.shuffleSession.addEventListener("click", shuffleCurrentSession);
els.favoriteCard.addEventListener("click", () => toggleFavorite().catch((error) => showToast(error.message)));
els.correctCard.addEventListener("click", () => recordResult("correct").catch((error) => showToast(error.message)));
els.wrongCard.addEventListener("click", () => recordResult("wrong").catch((error) => showToast(error.message)));

els.deckTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    state.source = tab.dataset.source || "all";
    startSession({ ordered: true }).catch((error) => showToast(error.message));
  });
});

els.chapterSelect.addEventListener("change", () => {
  state.chapter = els.chapterSelect.value || null;
  startSession({ ordered: true }).catch((error) => showToast(error.message));
});

els.typeSelect.addEventListener("change", () => {
  state.cardType = els.typeSelect.value || "";
  startSession({ ordered: true }).catch((error) => showToast(error.message));
});

els.query.addEventListener("input", () => {
  state.query = els.query.value;
  queueFilteredSession();
});

els.query.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    clearTimeout(filterTimer);
    state.query = els.query.value;
    startSession({ ordered: true }).catch((error) => showToast(error.message));
  }
});

els.prev.addEventListener("click", () => move(-1));
els.next.addEventListener("click", () => move(1));
els.reveal.addEventListener("click", toggleAnswer);
els.imageFrame.addEventListener("click", (event) => {
  if (isInteractiveClick(event.target)) return;
  toggleAnswer();
});
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
  .then(() => startSession({ ordered: true }))
  .catch((error) => showToast(error.message));
