const THEME_STORAGE_KEY = "flashcard-theme";
const DATA_URL = "./data/cards.json";
const FAVORITES_STORAGE_KEY = "flashcard-pages-favorites";
const REVIEWS_STORAGE_KEY = "flashcard-pages-reviews";

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
  allCards: [],
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

let toastTimer;

function readJsonStorage(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJsonStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // The page still works without persistence when storage is unavailable.
  }
}

function favoriteOverrides() {
  return readJsonStorage(FAVORITES_STORAGE_KEY, {});
}

function reviewOverrides() {
  return readJsonStorage(REVIEWS_STORAGE_KEY, {});
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

function cardAnswer(card) {
  return {
    title: card.answer_title || "",
    detail: card.answer_detail || card.caption_text || "",
  };
}

function shortText(value) {
  const text = String(value || "No caption").replace(/\s+/g, " ").trim();
  return text.length > 42 ? `${text.slice(0, 42)}...` : text;
}

function navigatorTitle(card) {
  const answer = cardAnswer(card);
  const title = answer.title || shortText(answer.detail || card.caption_text);
  return [card.figure_label, title].filter(Boolean).join(" ");
}

function sortedChapterRows(cards) {
  const chapters = new Map();
  for (const card of cards) {
    const chapter = card.chapter || "Unknown";
    const item = chapters.get(chapter) || { chapter, title: card.chapter_title || "", count: 0 };
    item.count += 1;
    chapters.set(chapter, item);
  }
  return Array.from(chapters.values()).sort((a, b) => {
    const an = a.chapter === "Unknown" ? Number.POSITIVE_INFINITY : Number(a.chapter);
    const bn = b.chapter === "Unknown" ? Number.POSITIVE_INFINITY : Number(b.chapter);
    if (an !== bn) return an - bn;
    return String(a.chapter).localeCompare(String(b.chapter));
  });
}

function computeSections() {
  const cards = state.allCards;
  return {
    all: cards.length,
    favorites: cards.filter((card) => card.is_favorite).length,
    past_exams: cards.filter((card) => card.is_past_exam).length,
    wrong: cards.filter((card) => card.last_review_result === "wrong").length,
    chapters: sortedChapterRows(cards),
  };
}

function loadSections() {
  state.sections = computeSections();
  els.sectionAll.textContent = state.sections.all;
  els.sectionFavorites.textContent = state.sections.favorites;
  els.sectionPastExams.textContent = state.sections.past_exams;
  els.sectionWrong.textContent = state.sections.wrong;
  els.chapterSelect.replaceChildren();

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Chapter";
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

function cardsForSource() {
  if (state.source === "favorites") return state.allCards.filter((card) => card.is_favorite);
  if (state.source === "past_exams") return state.allCards.filter((card) => card.is_past_exam);
  if (state.source === "wrong") return state.allCards.filter((card) => card.last_review_result === "wrong");
  if (state.source === "chapter") {
    const chapter = String(state.chapter || "");
    return state.allCards.filter((card) => String(card.chapter || "") === chapter);
  }
  return state.allCards.slice();
}

function startSession() {
  state.sessionId = `static-${Date.now()}`;
  state.cards = cardsForSource();
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
  const answerMeta = [card.figure_label, `p.${card.source_page}`].filter(Boolean).join(" | ");
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
  els.imageFrame.setAttribute("aria-label", state.flipped ? "Show question" : "Show answer");
  els.answerFace.classList.toggle("show", state.flipped);
  els.favoriteCard.classList.toggle("is-favorite", card.is_favorite);
  els.favoriteCard.textContent = card.is_favorite ? "Remove favorite" : "Favorite";
  els.reveal.innerHTML = state.flipped
    ? 'Question <span class="kbd">Space</span>'
    : 'Answer <span class="kbd">Space</span>';
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
      status.textContent = card.last_review_result === "correct" ? "Correct" : "Wrong";
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

function toggleFavorite() {
  const card = currentCard();
  if (!card) return;
  card.is_favorite = !card.is_favorite;
  const overrides = favoriteOverrides();
  overrides[card.card_id] = card.is_favorite;
  writeJsonStorage(FAVORITES_STORAGE_KEY, overrides);
  loadSections();
  showToast(card.is_favorite ? "Added to favorites" : "Removed from favorites");
  if (state.source === "favorites" && !card.is_favorite) {
    state.cards.splice(state.index, 1);
    if (state.index >= state.cards.length) state.index = Math.max(0, state.cards.length - 1);
  }
  render();
}

function recordResult(result) {
  const card = currentCard();
  if (!card || !state.sessionId) return;
  card.last_review_result = result;
  const reviews = reviewOverrides();
  reviews[card.card_id] = result;
  writeJsonStorage(REVIEWS_STORAGE_KEY, reviews);
  loadSections();
  showToast(result === "wrong" ? "Marked wrong" : "Marked correct");
  render();
}

async function loadDataset() {
  const response = await fetch(DATA_URL, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load ${DATA_URL}`);
  const payload = await response.json();
  const favorites = favoriteOverrides();
  const reviews = reviewOverrides();
  state.allCards = (payload.cards || []).map((card) => {
    const id = String(card.card_id);
    return {
      ...card,
      is_favorite: Object.prototype.hasOwnProperty.call(favorites, id)
        ? Boolean(favorites[id])
        : Boolean(card.is_favorite),
      is_past_exam: Boolean(card.is_past_exam),
      last_review_result: reviews[id] || card.last_review_result || "",
    };
  });
}

els.newSession.addEventListener("click", startSession);
els.shuffleSession.addEventListener("click", shuffleCurrentSession);
els.favoriteCard.addEventListener("click", toggleFavorite);
els.correctCard.addEventListener("click", () => recordResult("correct"));
els.wrongCard.addEventListener("click", () => recordResult("wrong"));
els.deckTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    state.source = tab.dataset.source || "all";
    startSession();
  });
});
els.chapterSelect.addEventListener("change", () => {
  state.source = "chapter";
  state.chapter = els.chapterSelect.value || state.chapter;
  startSession();
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

loadDataset()
  .then(() => {
    loadSections();
    startSession();
  })
  .catch((error) => showToast(error.message));
