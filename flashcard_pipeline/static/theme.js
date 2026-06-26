const THEME_STORAGE_KEY = "flashcard-theme";

function normalizeTheme(theme) {
  return theme === "dark" ? "dark" : "light";
}

export function currentTheme() {
  return normalizeTheme(document.documentElement.dataset.theme);
}

export function applyTheme(theme) {
  const nextTheme = normalizeTheme(theme);
  document.documentElement.dataset.theme = nextTheme;
  document.documentElement.style.colorScheme = nextTheme;

  const toggle = document.querySelector("#theme-toggle");
  if (!toggle) return;

  const isDark = nextTheme === "dark";
  const label = toggle.querySelector(".theme-toggle-text");
  if (label) label.textContent = isDark ? "Dark" : "Light";
  toggle.setAttribute("aria-pressed", String(isDark));
  toggle.setAttribute("aria-checked", String(isDark));
  toggle.setAttribute("title", isDark ? "Switch to light mode" : "Switch to dark mode");
}

export function initThemeToggle() {
  applyTheme(currentTheme());
  const toggle = document.querySelector("#theme-toggle");
  if (!toggle) return;

  toggle.addEventListener("click", () => {
    const nextTheme = currentTheme() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch {
      // The theme still changes for this page when storage is unavailable.
    }
    applyTheme(nextTheme);
  });
}
