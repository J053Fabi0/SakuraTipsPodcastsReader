"use strict";

const SCHEMA_VERSION = 1;
const WATCHED_THRESHOLD = 95;

const statusElement = document.getElementById("index-status");
const pendingList = document.getElementById("pending-list");
const watchedList = document.getElementById("watched-list");
const pendingPanel = document.getElementById("panel-pending");
const watchedPanel = document.getElementById("panel-watched");
const tabs = Array.from(document.querySelectorAll(".tab"));
const countElements = {
  pending: document.querySelector('[data-count="pending"]'),
  watched: document.querySelector('[data-count="watched"]'),
};
const sortSelect = document.getElementById("sort-select");
const sortDirection = document.getElementById("sort-direction");

let sortKey = "chapter";
let sortAscending = true;

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function progressPercent(podcast) {
  const duration = Number(podcast.duration);
  const progress = Number(podcast.progress);
  if (!Number.isFinite(duration) || duration <= 0 || !Number.isFinite(progress)) {
    return 0;
  }
  return clamp((progress / duration) * 100, 0, 100);
}

function formatPercent(value) {
  const rounded = Math.round(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}%`;
}

function chapterValue(podcast) {
  if (podcast.chapterNumber !== null && podcast.chapterNumber !== undefined) {
    const stored = Number(podcast.chapterNumber);
    if (Number.isInteger(stored) && stored >= 0) {
      return stored;
    }
  }
  const title = String(podcast.title || "");
  const match = title.match(
    /^\s*(\d+)\s*[.．]|[｜|]\s*(\d+)\s*[.．]|#\s*(\d+)/,
  );
  if (!match) {
    return null;
  }
  return Number(match[1] || match[2] || match[3]);
}

function difficultyValue(podcast) {
  const value = Number(podcast.difficulty);
  return Number.isInteger(value) && value >= 0 && value <= 5 ? value : 0;
}

function comparePodcasts(left, right) {
  const direction = sortAscending ? 1 : -1;
  if (sortKey === "difficulty") {
    const a = difficultyValue(left);
    const b = difficultyValue(right);
    if (a === 0 && b === 0) {
      return (
        (chapterValue(left) ?? Infinity) -
          (chapterValue(right) ?? Infinity) ||
        String(left.title).localeCompare(String(right.title))
      );
    }
    if (a === 0) {
      return 1;
    }
    if (b === 0) {
      return -1;
    }
    if (a !== b) {
      return (a - b) * direction;
    }
    return (
      (chapterValue(left) ?? Infinity) -
        (chapterValue(right) ?? Infinity) ||
      String(left.title).localeCompare(String(right.title))
    );
  }
  const a = chapterValue(left);
  const b = chapterValue(right);
  if (a === null && b === null) {
    return String(left.title).localeCompare(String(right.title)) * direction;
  }
  if (a === null) {
    return 1;
  }
  if (b === null) {
    return -1;
  }
  return (
    (a - b) * direction ||
    String(left.title).localeCompare(String(right.title)) * direction
  );
}

function sortedPodcasts(podcasts) {
  return [...podcasts].sort(comparePodcasts);
}

function difficultyLabel(podcast) {
  const value = difficultyValue(podcast);
  return value > 0
    ? `Dificultad: ${"★".repeat(value)}${"☆".repeat(5 - value)}`
    : "Dificultad: sin calificar";
}

function updateSortButton() {
  sortDirection.textContent = sortAscending ? "↑ Ascendente" : "↓ Descendente";
  sortDirection.setAttribute(
    "aria-label",
    sortAscending
      ? "Cambiar a orden descendente"
      : "Cambiar a orden ascendente",
  );
}

function createCard(podcast) {
  const percent = progressPercent(podcast);
  const link = document.createElement("a");
  link.className = "podcast-card";
  link.href = `podcast.html?id=${encodeURIComponent(podcast.youtubeId)}`;

  const top = document.createElement("div");
  top.className = "card-top";

  const title = document.createElement("h2");
  title.className = "card-title";
  title.textContent = podcast.title;

  const percentLabel = document.createElement("span");
  percentLabel.className = "card-percent";
  percentLabel.textContent = formatPercent(percent);

  top.append(title, percentLabel);

  const track = document.createElement("div");
  track.className = "progress-track";
  const fill = document.createElement("div");
  fill.className = "progress-fill";
  fill.style.width = `${percent}%`;
  track.appendChild(fill);

  const meta = document.createElement("p");
  meta.className = "card-meta";
  const lines = Array.isArray(podcast.japanese) ? podcast.japanese.length : 0;
  meta.textContent = `${formatDuration(podcast.duration)} · ${lines} líneas · ${difficultyLabel(podcast)}`;

  link.append(top, track, meta);
  return link;
}

function renderList(container, podcasts, emptyMessage) {
  container.replaceChildren();
  if (podcasts.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = emptyMessage;
    container.appendChild(empty);
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const podcast of podcasts) {
    fragment.appendChild(createCard(podcast));
  }
  container.appendChild(fragment);
}

function render(data) {
  const podcasts = Array.isArray(data.podcasts) ? data.podcasts : [];
  const pending = sortedPodcasts(
    podcasts.filter((podcast) => progressPercent(podcast) < WATCHED_THRESHOLD),
  );
  const watched = sortedPodcasts(
    podcasts.filter((podcast) => progressPercent(podcast) >= WATCHED_THRESHOLD),
  );

  countElements.pending.textContent = String(pending.length);
  countElements.watched.textContent = String(watched.length);

  renderList(
    pendingList,
    pending,
    podcasts.length === 0
      ? "Todavía no hay podcasts. Agrega uno desde la línea de comandos."
      : "No quedan podcasts pendientes. ¡Buen trabajo!",
  );
  renderList(
    watchedList,
    watched,
    "Aún no has terminado ningún podcast. Los verás aquí al alcanzar el 95%.",
  );

  statusElement.hidden = true;
}

function selectTab(tabName) {
  for (const tab of tabs) {
    const active = tab.dataset.tab === tabName;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  pendingPanel.hidden = tabName !== "pending";
  watchedPanel.hidden = tabName !== "watched";
}

async function load() {
  try {
    const response = await fetch("database.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    if (data.schemaVersion !== SCHEMA_VERSION) {
      throw new Error(`schemaVersion no soportada: ${data.schemaVersion}`);
    }
    render(data);
  } catch (error) {
    console.error(error);
    statusElement.hidden = false;
    statusElement.classList.add("is-error");
    statusElement.textContent =
      "No se pudo cargar database.json. Inicia el servidor local e inténtalo de nuevo.";
  }
}

for (const tab of tabs) {
  tab.addEventListener("click", () => selectTab(tab.dataset.tab));
}

sortSelect.addEventListener("change", () => {
  sortKey = sortSelect.value;
  load();
});

sortDirection.addEventListener("click", () => {
  sortAscending = !sortAscending;
  updateSortButton();
  load();
});

updateSortButton();
load();
