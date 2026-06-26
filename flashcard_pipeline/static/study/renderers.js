const TYPE_LABELS = {
  image: "이미지",
  multiple_choice: "객관식",
  short_answer: "주관식",
};

function setHidden(node, hidden) {
  node.classList.toggle("hidden", hidden);
}

function clearNode(node) {
  node.replaceChildren();
}

function text(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function mediaItems(card) {
  return Array.isArray(card.media) ? card.media.filter((item) => item.kind === "image" && item.src) : [];
}

function answerText(card) {
  return text(card.answer?.text);
}

function answerExplanation(card) {
  return text(card.answer?.explanation);
}

export function navigatorTitle(card) {
  const label = text(card.meta?.sourceLabel);
  const prompt = text(card.prompt?.text);
  const answer = answerText(card);
  const body = prompt || answer || card.id;
  const clipped = body.length > 46 ? `${body.slice(0, 46)}...` : body;
  return [label, clipped].filter(Boolean).join(" ");
}

export function answerMeta(card) {
  const parts = [
    text(card.meta?.sourceLabel),
    card.meta?.sourcePage ? `p.${card.meta.sourcePage}` : "",
    TYPE_LABELS[card.type] || card.type,
  ];
  return parts.filter(Boolean).join(" | ");
}

function renderMedia(card, els) {
  const images = mediaItems(card);
  clearNode(els.images);
  setHidden(els.images, images.length === 0);
  els.images.classList.toggle("multi", images.length > 1);
  for (const item of images) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.src = item.src;
    image.alt = item.alt || "Flashcard image";
    els.images.appendChild(image);
  }
}

function renderChoices(card, els, state) {
  clearNode(els.choiceList);
  const choices = Array.isArray(card.choices) ? card.choices : [];
  setHidden(els.choiceList, choices.length === 0 || card.type !== "multiple_choice");
  for (const choice of choices) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "choice-option";
    button.dataset.choiceId = choice.id;
    button.textContent = choice.text;
    button.classList.toggle("selected", state.selectedChoiceIds.has(choice.id));
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      if (state.revealed) return;
      if (state.selectedChoiceIds.has(choice.id)) {
        state.selectedChoiceIds.delete(choice.id);
      } else {
        state.selectedChoiceIds.add(choice.id);
      }
      renderChoices(card, els, state);
    });
    els.choiceList.appendChild(button);
  }
}

function renderShortAnswer(card, els, state) {
  const isShortAnswer = card.type === "short_answer";
  setHidden(els.shortAnswer, !isShortAnswer);
  if (!isShortAnswer) {
    els.shortAnswer.value = "";
    return;
  }
  els.shortAnswer.value = state.shortAnswerText;
  els.shortAnswer.oninput = () => {
    state.shortAnswerText = els.shortAnswer.value;
  };
  els.shortAnswer.onclick = (event) => event.stopPropagation();
}

export function renderQuestion(card, els, state) {
  els.questionFace.className = `question-face ${card.type}`;
  els.questionType.textContent = TYPE_LABELS[card.type] || card.type;
  els.questionPrompt.textContent = text(card.prompt?.text);
  setHidden(els.questionPrompt, !text(card.prompt?.text));
  renderMedia(card, els);
  renderChoices(card, els, state);
  renderShortAnswer(card, els, state);
}

function correctChoiceText(card) {
  const ids = new Set((card.answer?.choiceIds || []).map(String));
  return (card.choices || [])
    .filter((choice) => ids.has(String(choice.id)))
    .map((choice) => choice.text)
    .join(", ");
}

export function renderAnswer(card, els) {
  const meta = answerMeta(card);
  const answer = answerText(card);
  const explanation = answerExplanation(card);
  let title = answer;
  let detail = explanation;

  if (card.type === "multiple_choice") {
    title = correctChoiceText(card) || answer || "정답";
    detail = explanation;
  } else if (answer.length > 90) {
    title = "정답";
    detail = [answer, explanation].filter(Boolean).join("\n\n");
  } else if (!title && explanation) {
    title = "정답";
    detail = explanation;
  }

  els.answerMeta.textContent = meta;
  setHidden(els.answerMeta, !meta);
  els.answerTitle.textContent = title;
  setHidden(els.answerTitle, !title);
  els.answerDetail.textContent = detail;
  setHidden(els.answerDetail, !detail);
  els.answerFace.classList.toggle("no-title", !title);
}
