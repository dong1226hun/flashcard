const STATIC_DATA_URL = "./data/cards.json";
const FAVORITES_STORAGE_KEY = "flashcard-template-favorites";
const REVIEWS_STORAGE_KEY = "flashcard-template-reviews";
const CARD_TYPES = new Set(["image", "multiple_choice", "short_answer"]);

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "요청에 실패했습니다");
  return data;
}

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
    // Static mode remains usable without persistence.
  }
}

function ensureArray(value) {
  return Array.isArray(value) ? value : [];
}

export function normalizeCard(card, index = 0) {
  const id = String(card.id || "");
  if (!id) throw new Error(`Card at index ${index} is missing id`);
  if (!CARD_TYPES.has(card.type)) throw new Error(`Card ${id} has invalid type`);
  if (!card.prompt || typeof card.prompt.text !== "string") {
    throw new Error(`Card ${id} is missing prompt.text`);
  }
  if (!card.answer || typeof card.answer !== "object") {
    throw new Error(`Card ${id} is missing answer`);
  }

  return {
    ...card,
    id,
    card_id: card.card_id ?? Number(id),
    media: ensureArray(card.media),
    choices: ensureArray(card.choices),
    answer: {
      text: String(card.answer.text || ""),
      choiceIds: ensureArray(card.answer.choiceIds).map(String),
      explanation: String(card.answer.explanation || ""),
    },
    meta: {
      chapter: String(card.meta?.chapter || "Unknown"),
      chapterTitle: String(card.meta?.chapterTitle || ""),
      sourcePage: card.meta?.sourcePage ?? "",
      sourceLabel: String(card.meta?.sourceLabel || ""),
      tags: ensureArray(card.meta?.tags),
    },
    review: {
      favorite: Boolean(card.review?.favorite),
      pastExam: Boolean(card.review?.pastExam),
      lastResult: String(card.review?.lastResult || ""),
    },
    sortOrder: Number.isFinite(Number(card.sortOrder)) ? Number(card.sortOrder) : index,
  };
}

function sortedChapterRows(cards) {
  const chapters = new Map();
  for (const card of cards) {
    const chapter = card.meta.chapter || "Unknown";
    const current = chapters.get(chapter) || {
      chapter,
      title: card.meta.chapterTitle || "",
      count: 0,
    };
    current.count += 1;
    chapters.set(chapter, current);
  }
  return Array.from(chapters.values()).sort((a, b) => {
    const an = a.chapter === "Unknown" ? Number.POSITIVE_INFINITY : Number(a.chapter);
    const bn = b.chapter === "Unknown" ? Number.POSITIVE_INFINITY : Number(b.chapter);
    if (an !== bn) return an - bn;
    return String(a.chapter).localeCompare(String(b.chapter));
  });
}

function computeSections(cards) {
  return {
    all: cards.length,
    favorites: cards.filter((card) => card.review.favorite).length,
    past_exams: cards.filter((card) => card.review.pastExam).length,
    wrong: cards.filter((card) => card.review.lastResult === "wrong").length,
    chapters: sortedChapterRows(cards),
  };
}

function orderedCards(cards) {
  return cards.slice().sort((a, b) => {
    if (a.sortOrder !== b.sortOrder) return a.sortOrder - b.sortOrder;
    return Number(a.card_id || 0) - Number(b.card_id || 0);
  });
}

function shuffle(cards) {
  const next = cards.slice();
  for (let i = next.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [next[i], next[j]] = [next[j], next[i]];
  }
  return next;
}

function matchesQuery(card, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return true;
  return [
    card.prompt.text,
    card.answer.text,
    card.answer.explanation,
    card.meta.sourceLabel,
    card.source?.captionText,
    card.source?.notes,
  ].some((value) => String(value || "").toLowerCase().includes(needle));
}

function applyCardFilters(cards, { chapter, cardType, query } = {}) {
  let next = cards;
  if (chapter) {
    next = next.filter((card) => card.meta.chapter === String(chapter));
  }
  if (cardType && CARD_TYPES.has(cardType)) {
    next = next.filter((card) => card.type === cardType);
  }
  if (query && String(query).trim()) {
    next = next.filter((card) => matchesQuery(card, query));
  }
  return next;
}

export function createApiProvider() {
  return {
    async loadSections() {
      return fetchJson("/api/study/sections");
    },

    async startSession({ source, chapter, cardType, query, ordered }) {
      const session = await fetchJson("/api/study/session", {
        method: "POST",
        body: JSON.stringify({
          count: "all",
          source,
          chapter,
          card_type: cardType,
          q: query,
          ordered,
        }),
      });
      return {
        ...session,
        cards: ensureArray(session.cards).map(normalizeCard),
      };
    },

    async setFavorite(card, favorite) {
      return fetchJson("/api/study/favorite", {
        method: "POST",
        body: JSON.stringify({ card_id: card.card_id, favorite }),
      });
    },

    async recordResult(sessionId, card, result) {
      return fetchJson("/api/study/review", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId, card_id: card.card_id, result }),
      });
    },
  };
}

export function createStaticProvider() {
  const state = {
    loaded: false,
    allCards: [],
  };

  async function loadDataset() {
    if (state.loaded) return;
    const response = await fetch(STATIC_DATA_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`Could not load ${STATIC_DATA_URL}`);
    const payload = await response.json();
    const favorites = readJsonStorage(FAVORITES_STORAGE_KEY, {});
    const reviews = readJsonStorage(REVIEWS_STORAGE_KEY, {});
    state.allCards = ensureArray(payload.cards).map((rawCard, index) => {
      const card = normalizeCard(rawCard, index);
      if (Object.prototype.hasOwnProperty.call(favorites, card.id)) {
        card.review.favorite = Boolean(favorites[card.id]);
      }
      if (Object.prototype.hasOwnProperty.call(reviews, card.id)) {
        card.review.lastResult = String(reviews[card.id] || "");
      }
      return card;
    });
    state.loaded = true;
  }

  function cardsForSource(source, filters = {}) {
    let cards = state.allCards;
    if (source === "favorites") cards = cards.filter((card) => card.review.favorite);
    if (source === "past_exams") cards = cards.filter((card) => card.review.pastExam);
    if (source === "wrong") cards = cards.filter((card) => card.review.lastResult === "wrong");
    if (source === "chapter") {
      const chapter = filters.chapter;
      cards = cards.filter((card) => card.meta.chapter === String(chapter || ""));
    }
    return orderedCards(applyCardFilters(cards, filters));
  }

  return {
    async loadSections() {
      await loadDataset();
      return computeSections(state.allCards);
    },

    async startSession({ source, chapter, cardType, query, ordered }) {
      await loadDataset();
      const cards = cardsForSource(source, { chapter, cardType, query });
      return {
        session_id: `static-${Date.now()}`,
        card_count: cards.length,
        source,
        chapter,
        cards: ordered ? cards : shuffle(cards),
      };
    },

    async setFavorite(card, favorite) {
      await loadDataset();
      const target = state.allCards.find((item) => item.id === card.id);
      if (target) target.review.favorite = Boolean(favorite);
      const favorites = readJsonStorage(FAVORITES_STORAGE_KEY, {});
      favorites[card.id] = Boolean(favorite);
      writeJsonStorage(FAVORITES_STORAGE_KEY, favorites);
      return { id: card.id, card_id: card.card_id, is_favorite: Boolean(favorite) };
    },

    async recordResult(sessionId, card, result) {
      await loadDataset();
      const target = state.allCards.find((item) => item.id === card.id);
      if (target) target.review.lastResult = result;
      const reviews = readJsonStorage(REVIEWS_STORAGE_KEY, {});
      reviews[card.id] = result;
      writeJsonStorage(REVIEWS_STORAGE_KEY, reviews);
      return { id: card.id, card_id: card.card_id, result, session_id: sessionId };
    },
  };
}
