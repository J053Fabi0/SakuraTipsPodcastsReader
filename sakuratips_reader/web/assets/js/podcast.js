"use strict";

const SCHEMA_VERSION = 1;
const AUTOSAVE_INTERVAL_MS = 5000;

const elements = {
  title: document.getElementById("podcast-title"),
  meta: document.getElementById("podcast-meta"),
  youtubeLink: document.getElementById("youtube-link"),
  sakuratipsLink: document.getElementById("sakuratips-link"),
  lyricsViewport: document.getElementById("lyrics-viewport"),
  lyrics: document.getElementById("lyrics"),
  lyricsStatus: document.getElementById("lyrics-status"),
  audio: document.getElementById("audio"),
  seek: document.getElementById("seek"),
  currentTime: document.getElementById("current-time"),
  totalTime: document.getElementById("total-time"),
  playPause: document.getElementById("play-pause"),
  back1: document.getElementById("back-1"),
  back3: document.getElementById("back-3"),
  forward1: document.getElementById("forward-1"),
  forward3: document.getElementById("forward-3"),
  saveStatus: document.getElementById("save-status"),
};

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let podcast = null;
let units = [];
let revealed = new Set();
let focusedIndex = -1;
let duration = 0;
let restoring = true;
let lastSavedProgress = null;
let saveStatusTimer = null;

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatPercent(value) {
  const rounded = Math.round(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}%`;
}

function setSaveStatus(message) {
  elements.saveStatus.textContent = message;
  if (saveStatusTimer) {
    clearTimeout(saveStatusTimer);
  }
  saveStatusTimer = setTimeout(() => {
    elements.saveStatus.textContent = "";
  }, 3500);
}

function appendFurigana(container, tokens) {
  if (!Array.isArray(tokens)) {
    return;
  }
  for (const token of tokens) {
    if (!token || typeof token.text !== "string") {
      continue;
    }
    if (token.reading) {
      const ruby = document.createElement("ruby");
      ruby.appendChild(document.createTextNode(token.text));
      const rt = document.createElement("rt");
      rt.textContent = token.reading;
      ruby.appendChild(rt);
      container.appendChild(ruby);
    } else {
      container.appendChild(document.createTextNode(token.text));
    }
  }
}

function setRevealed(index, shouldReveal) {
  const unit = units[index];
  if (!unit) {
    return;
  }
  if (shouldReveal) {
    revealed.add(index);
  } else {
    revealed.delete(index);
  }
  unit.classList.toggle("revealed", shouldReveal);
  unit.setAttribute("aria-pressed", String(shouldReveal));
}

function toggleUnit(index) {
  setRevealed(index, !revealed.has(index));
}

function activateUnit(index) {
  if (index !== focusedIndex) {
    units[index].scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "center",
    });
    return;
  }
  toggleUnit(index);
}

function renderLyrics() {
  elements.lyrics.replaceChildren();
  units = [];

  const fragment = document.createDocumentFragment();
  podcast.japanese.forEach((japaneseLine, index) => {
    const unit = document.createElement("section");
    unit.className = "unit";
    unit.dataset.index = String(index);
    unit.tabIndex = 0;
    unit.setAttribute("role", "button");
    unit.setAttribute("aria-pressed", "false");

    const japanese = document.createElement("div");
    japanese.className = "ja";
    appendFurigana(japanese, podcast.furigana[index]);

    const english = document.createElement("div");
    english.className = "en";
    english.textContent = podcast.english[index] || "";

    unit.append(japanese, english);
    unit.addEventListener("click", () => activateUnit(index));
    unit.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activateUnit(index);
      }
    });

    fragment.appendChild(unit);
    units.push(unit);
  });

  elements.lyrics.appendChild(fragment);
  elements.lyricsStatus.hidden = true;
}

function setFocused(index) {
  if (index === focusedIndex) {
    return;
  }
  if (focusedIndex >= 0 && units[focusedIndex]) {
    units[focusedIndex].classList.remove("focused");
  }
  focusedIndex = index;
  if (index >= 0 && units[index]) {
    units[index].classList.add("focused");
  }
}

function updateFocus() {
  if (units.length === 0) {
    return;
  }
  const viewportRect = elements.lyricsViewport.getBoundingClientRect();
  const center = viewportRect.top + viewportRect.height / 2;
  let bestIndex = -1;
  let bestDistance = Number.POSITIVE_INFINITY;

  units.forEach((unit, index) => {
    const rect = unit.getBoundingClientRect();
    const unitCenter = rect.top + rect.height / 2;
    const distance = Math.abs(unitCenter - center);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });

  if (bestIndex >= 0) {
    setFocused(bestIndex);
  }
}

let scrollTicking = false;
elements.lyricsViewport.addEventListener("scroll", () => {
  if (scrollTicking) {
    return;
  }
  scrollTicking = true;
  window.requestAnimationFrame(() => {
    updateFocus();
    scrollTicking = false;
  });
});

window.addEventListener("resize", () => {
  window.requestAnimationFrame(updateFocus);
});

function currentProgress() {
  return clamp(Number(elements.audio.currentTime) || 0, 0, duration);
}

async function saveProgress({ force = false, beacon = false, value = null } = {}) {
  if (!podcast || restoring || !Number.isFinite(duration) || duration <= 0) {
    return;
  }
  const progressValue = clamp(
    value === null ? currentProgress() : Number(value),
    0,
    duration,
  );
  if (!Number.isFinite(progressValue)) {
    return;
  }
  if (
    !force &&
    lastSavedProgress !== null &&
    Math.abs(progressValue - lastSavedProgress) < 0.4
  ) {
    return;
  }

  const url = `/api/progress/${encodeURIComponent(podcast.youtubeId)}`;
  const payload = JSON.stringify({ progress: progressValue });

  if (beacon && typeof navigator.sendBeacon === "function") {
    const blob = new Blob([payload], { type: "application/json" });
    const accepted = navigator.sendBeacon(url, blob);
    if (accepted) {
      lastSavedProgress = progressValue;
      return;
    }
  }

  try {
    const response = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: payload,
      keepalive: true,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    lastSavedProgress = progressValue;
    setSaveStatus("Progreso guardado");
  } catch (error) {
    console.warn("No se pudo guardar el progreso", error);
    setSaveStatus("No se pudo guardar el progreso");
  }
}

function updateTimeUI() {
  const current = currentProgress();
  elements.currentTime.textContent = formatTime(current);
  elements.totalTime.textContent = formatTime(duration);
  elements.seek.value = String(current);
}

function seekTo(seconds) {
  if (!Number.isFinite(duration) || duration <= 0) {
    return;
  }
  const target = clamp(seconds, 0, duration);
  try {
    elements.audio.currentTime = target;
  } catch (error) {
    console.warn("No se pudo cambiar la posicion", error);
  }
  updateTimeUI();
}

function seekBy(delta) {
  seekTo(currentProgress() + delta);
}

function updatePlayButton() {
  const playing = !elements.audio.paused && !elements.audio.ended;
  elements.playPause.textContent = playing ? "❚❚" : "▶";
  elements.playPause.setAttribute(
    "aria-label",
    playing ? "Pausar" : "Reproducir",
  );
}

function setupPlayer() {
  duration = Number(podcast.duration) || 0;
  elements.audio.src = podcast.audioFile;
  elements.seek.max = String(duration);
  elements.seek.disabled = false;
  elements.totalTime.textContent = formatTime(duration);

  elements.audio.addEventListener("loadedmetadata", () => {
    const realDuration = Number(elements.audio.duration);
    const maximum = Number.isFinite(realDuration) && realDuration > 0
      ? Math.min(duration, realDuration)
      : duration;
    const stored = clamp(Number(podcast.progress) || 0, 0, maximum);
    if (stored > 0) {
      try {
        elements.audio.currentTime = stored;
      } catch (error) {
        console.warn("No se pudo restaurar el progreso", error);
      }
    }
    restoring = false;
    updateTimeUI();
    updatePlayButton();
  });

  elements.audio.addEventListener("timeupdate", () => {
    if (!restoring) {
      updateTimeUI();
    }
  });

  elements.audio.addEventListener("play", updatePlayButton);
  elements.audio.addEventListener("pause", () => {
    updatePlayButton();
    saveProgress();
  });
  elements.audio.addEventListener("seeked", () => {
    updateTimeUI();
    saveProgress();
  });
  elements.audio.addEventListener("ended", () => {
    updatePlayButton();
    updateTimeUI();
    saveProgress({ force: true, value: duration });
  });
  elements.audio.addEventListener("error", () => {
    setSaveStatus("No se pudo cargar el archivo de audio.");
  });

  elements.playPause.addEventListener("click", () => {
    if (elements.audio.paused || elements.audio.ended) {
      elements.audio.play().catch((error) => {
        console.warn("No se pudo reproducir", error);
        setSaveStatus("No se pudo reproducir el audio.");
      });
    } else {
      elements.audio.pause();
    }
  });

  elements.back1.addEventListener("click", () => seekBy(-1));
  elements.back3.addEventListener("click", () => seekBy(-3));
  elements.forward1.addEventListener("click", () => seekBy(1));
  elements.forward3.addEventListener("click", () => seekBy(3));

  elements.seek.addEventListener("input", () => {
    if (restoring) {
      return;
    }
    seekTo(Number(elements.seek.value));
  });
  elements.seek.addEventListener("change", () => saveProgress());

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      saveProgress({ force: true, beacon: true });
    }
  });
  window.addEventListener("pagehide", () => {
    saveProgress({ beacon: true });
  });

  window.setInterval(() => {
    if (!elements.audio.paused && !elements.audio.ended) {
      saveProgress();
    }
  }, AUTOSAVE_INTERVAL_MS);

  updatePlayButton();
}

function renderHeader() {
  document.title = `${podcast.title} · SakuraTips Reader`;
  elements.title.textContent = podcast.title;
  const lines = podcast.japanese.length;
  const percent = duration > 0
    ? clamp((Number(podcast.progress) / duration) * 100, 0, 100)
    : 0;
  elements.meta.textContent = `${formatTime(duration)} · ${lines} líneas · ${formatPercent(percent)}`;
  elements.youtubeLink.href = podcast.youtubeUrl;
  elements.sakuratipsLink.href = podcast.sakuratipsUrl;
}

function showFatalError(message) {
  elements.lyricsStatus.hidden = false;
  elements.lyricsStatus.classList.add("is-error");
  elements.lyricsStatus.textContent = message;
}

async function load() {
  const youtubeId = new URLSearchParams(window.location.search).get("id");
  if (!youtubeId) {
    showFatalError("Falta el identificador del podcast en la URL.");
    return;
  }

  try {
    const response = await fetch("database.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    if (data.schemaVersion !== SCHEMA_VERSION) {
      throw new Error(`schemaVersion no soportada: ${data.schemaVersion}`);
    }
    podcast = data.podcasts.find((entry) => entry.youtubeId === youtubeId);
    if (!podcast) {
      showFatalError("No se encontró el podcast solicitado.");
      return;
    }

    duration = Number(podcast.duration) || 0;
    renderHeader();
    renderLyrics();
    setupPlayer();
    window.requestAnimationFrame(updateFocus);
  } catch (error) {
    console.error(error);
    showFatalError(
      "No se pudo cargar database.json. Inicia el servidor local e inténtalo de nuevo.",
    );
  }
}

load();
