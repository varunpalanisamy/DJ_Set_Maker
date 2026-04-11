import WaveSurfer from "https://cdn.jsdelivr.net/npm/wavesurfer.js@7/dist/wavesurfer.esm.js";

const STEMS = ["vocals", "drums", "bass", "other"];
const TRACKS = [
  { group: "song_a", stem: "vocals", label: "Song A Vocals" },
  { group: "song_a", stem: "drums", label: "Song A Drums" },
  { group: "song_a", stem: "bass", label: "Song A Bass" },
  { group: "song_a", stem: "other", label: "Song A Music" },
  { group: "song_b", stem: "vocals", label: "Song B Vocals" },
  { group: "song_b", stem: "drums", label: "Song B Drums" },
  { group: "song_b", stem: "bass", label: "Song B Bass" },
  { group: "song_b", stem: "other", label: "Song B Music" },
];
const MIX_TRACKS = [
  { group: "song_a", stem: "mix", label: "Song A Mix" },
  { group: "song_b", stem: "mix", label: "Song B Mix" },
];

const COLORS = {
  song_a: {
    vocals: { wave: "rgba(139,245,220,0.42)", progress: "rgba(57,208,191,0.92)" },
    drums: { wave: "rgba(243,177,90,0.40)", progress: "rgba(220,130,30,0.9)" },
    bass: { wave: "rgba(190,120,245,0.40)", progress: "rgba(158,79,235,0.92)" },
    other: { wave: "rgba(99,178,255,0.38)", progress: "rgba(60,144,236,0.92)" },
  },
  song_b: {
    vocals: { wave: "rgba(139,245,220,0.26)", progress: "rgba(57,208,191,0.72)" },
    drums: { wave: "rgba(243,177,90,0.24)", progress: "rgba(220,130,30,0.74)" },
    bass: { wave: "rgba(190,120,245,0.24)", progress: "rgba(158,79,235,0.74)" },
    other: { wave: "rgba(99,178,255,0.22)", progress: "rgba(60,144,236,0.74)" },
  },
};

let waves = {};
let currentSession = null;
let masterAudio = null;
let zoomPxPerSec = 90;
let animationFrameId = 0;
let currentStyle = "Style_A";
let currentRender = null;
let waveformsReady = false;
const groupCollapsed = { song_a: false, song_b: false };
let isDraggingPlayhead = false;
let playheadPointerId = null;
let resumePlaybackAfterDrag = false;
let lastManualViewportInteractionAt = 0;

const viewportEl = document.getElementById("stem-stage-viewport");
const stageEl = document.getElementById("stem-stage-content");
const timelineEl = document.getElementById("stem-timeline-track");
const transitionBandEl = document.getElementById("stem-transition-band");
const styleEnvelopeEl = document.getElementById("stem-style-envelope");
const playheadEl = document.getElementById("stem-global-playhead");
const scrollbarEl = document.getElementById("stem-scrollbar");
const currentTimeEl = document.getElementById("stem-current-time");
const totalTimeEl = document.getElementById("stem-total-time");
const playButtonEl = document.getElementById("stem-play-btn");
const zoomSliderEl = document.getElementById("stem-zoom");
const statusEl = document.getElementById("stem-status");
const groupTitleAEl = document.getElementById("stem-group-title-a");
const groupTitleBEl = document.getElementById("stem-group-title-b");
const collapseAButton = document.getElementById("stem-collapse-a");
const collapseBButton = document.getElementById("stem-collapse-b");

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function debugLog(message) {
  window.appendStemDebug?.(message);
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function setStemStatus(message, type = "") {
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.className = "status";
  if (type) statusEl.classList.add(type);
}

function setStyleButtonsDisabled(disabled) {
  ["btn-style-a", "btn-style-b", "btn-style-c"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
  });
}

function destroyWaveforms() {
  Object.values(waves).forEach((wave) => wave?.destroy());
  waves = {};
}

function trackKey(group, stem) {
  return `${group}:${stem}`;
}

function getTrackWidth() {
  if (!currentSession) return 0;
  return Math.max(viewportEl?.clientWidth || 800, Math.ceil(currentSession.timing.total_duration * zoomPxPerSec));
}

function transportTimeToDisplayTime(timeSeconds) {
  if (!currentSession) return timeSeconds;
  const {
    overlay_start_time,
    transition_end_time,
    transition_duration_time,
    song_b_source_transition_time,
  } = currentSession.timing;

  if (timeSeconds <= overlay_start_time) {
    return timeSeconds;
  }

  const sourceTransitionEnd = overlay_start_time + song_b_source_transition_time;
  if (timeSeconds <= transition_end_time && transition_duration_time > 0) {
    const progress = (timeSeconds - overlay_start_time) / transition_duration_time;
    return overlay_start_time + (progress * song_b_source_transition_time);
  }

  return sourceTransitionEnd + (timeSeconds - transition_end_time);
}

function displayTimeToTransportTime(displayTimeSeconds) {
  if (!currentSession) return displayTimeSeconds;
  const {
    overlay_start_time,
    transition_end_time,
    transition_duration_time,
    song_b_source_transition_time,
  } = currentSession.timing;

  if (displayTimeSeconds <= overlay_start_time) {
    return displayTimeSeconds;
  }

  const sourceTransitionEnd = overlay_start_time + song_b_source_transition_time;
  if (displayTimeSeconds <= sourceTransitionEnd && song_b_source_transition_time > 0) {
    const progress = (displayTimeSeconds - overlay_start_time) / song_b_source_transition_time;
    return overlay_start_time + (progress * transition_duration_time);
  }

  return transition_end_time + (displayTimeSeconds - sourceTransitionEnd);
}

function timeToPixels(timeSeconds) {
  return Math.max(0, transportTimeToDisplayTime(timeSeconds) * zoomPxPerSec);
}

function pixelsToTime(pixelOffset) {
  if (!currentSession) return 0;
  const displayTime = clamp(pixelOffset / zoomPxPerSec, 0, currentSession.timing.total_duration);
  return clamp(displayTimeToTransportTime(displayTime), 0, currentSession.timing.total_duration);
}

function getDesiredInitialZoom() {
  if (!currentSession || !viewportEl) return zoomPxPerSec;
  const transitionDuration = Math.max(0.5, currentSession.timing.transition_duration_time);
  const targetViewportWidth = Math.max(480, viewportEl.clientWidth || 0);
  return clamp((targetViewportWidth * 0.6) / transitionDuration, 40, 240);
}

function getFitToScreenZoom() {
  if (!currentSession || !viewportEl) return 1;
  const viewportWidth = Math.max(480, viewportEl.clientWidth || 0);
  return clamp(viewportWidth / Math.max(1, currentSession.timing.total_duration), 1, 240);
}

function getRulerInterval() {
  if (zoomPxPerSec >= 180) return 0.5;
  if (zoomPxPerSec >= 110) return 1;
  if (zoomPxPerSec >= 70) return 2;
  return 5;
}

function syncScrollbarToViewport() {
  if (!viewportEl || !scrollbarEl) return;
  const maxScroll = Math.max(0, stageEl.scrollWidth - viewportEl.clientWidth);
  scrollbarEl.max = String(Math.max(maxScroll, 1));
  scrollbarEl.value = String(Math.min(maxScroll, viewportEl.scrollLeft));
}

function scrollViewportToPlayhead(playheadX, forceCenter = false) {
  if (!viewportEl || !stageEl) return;
  const viewportWidth = viewportEl.clientWidth;
  const maxScroll = Math.max(0, stageEl.scrollWidth - viewportWidth);
  const visibleX = playheadX - viewportEl.scrollLeft;
  const shouldCenter =
    forceCenter
    || visibleX > viewportWidth * 0.72
    || visibleX < viewportWidth * 0.28;
  if (!shouldCenter) return;

  viewportEl.scrollLeft = clamp(playheadX - (viewportWidth / 2), 0, maxScroll);
  syncScrollbarToViewport();
}

function centerTransitionInView() {
  if (!currentSession || !viewportEl || !stageEl) return;
  const transitionMidpoint =
    (currentSession.timing.song_a_exit_time + currentSession.timing.transition_end_time) / 2;
  scrollViewportToPlayhead(timeToPixels(transitionMidpoint), true);
  updatePlayhead();
}

function updatePlayhead() {
  if (!currentSession || !viewportEl || !playheadEl) return;
  const currentTime = masterAudio ? masterAudio.currentTime : 0;
  const playheadX = timeToPixels(currentTime);
  if (
    masterAudio
    && !masterAudio.paused
    && !isDraggingPlayhead
    && (Date.now() - lastManualViewportInteractionAt) > 800
  ) {
    scrollViewportToPlayhead(playheadX);
  }
  playheadEl.style.left = `${playheadX - viewportEl.scrollLeft}px`;
  playheadEl.style.display = "block";
  currentTimeEl.textContent = formatTime(currentTime);
}

function getAutomationPlan(group, stem, styleName) {
  const start = currentSession?.timing.song_a_exit_time || 0;
  const end = currentSession?.timing.transition_end_time || start;
  const mid = start + (end - start) * 0.5;
  const points = [
    { time: 0, level: group === "song_a" ? 1 : 0 },
    { time: start, level: group === "song_a" ? 1 : 0.08 },
  ];
  let filtered = false;

  if (group === "song_a") {
    if (styleName === "Style_B") {
      points.push({ time: end, level: 0.04 });
    } else if (styleName === "Style_C" && stem === "vocals") {
      points.push({ time: start + 0.05, level: 0 });
      points.push({ time: end, level: 0 });
    } else if (["bass", "drums"].includes(stem)) {
      points.push({ time: mid, level: styleName === "Style_C" ? 0.14 : 0.2 });
      points.push({ time: end, level: 0.06 });
    } else if (styleName === "Style_A" && stem === "vocals") {
      points.push({ time: end - Math.min(2.2, Math.max(0.8, end - start)), level: 1 });
      points.push({ time: end, level: 0.08 });
    } else {
      points.push({ time: end, level: 0.7 });
    }
    filtered = ["bass", "other"].includes(stem) && ["Style_A", "Style_C"].includes(styleName);
  } else {
    points.push({ time: currentSession?.timing.overlay_start_time || 0, level: 0.04 });
    points.push({ time: currentSession?.timing.song_b_entry_on_timeline || start, level: stem === "vocals" ? 0.72 : 0.9 });
    points.push({ time: end, level: 1 });
  }

  return { points, filtered };
}

function buildOverlaySvg(group, stem, styleName) {
  if (!currentSession) return "";
  const width = getTrackWidth();
  const height = 72;
  const { points, filtered } = getAutomationPlan(group, stem, styleName);
  const path = points
    .map((point, index) => {
      const x = clamp(point.time * zoomPxPerSec, 0, width);
      const y = 10 + (1 - point.level) * 50;
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");

  const filterBadge = filtered
    ? `<g class="stem-overlay-filter"><circle cx="${Math.max(18, currentSession.timing.song_a_exit_time * zoomPxPerSec + 18)}" cy="14" r="9"></circle><text x="${Math.max(18, currentSession.timing.song_a_exit_time * zoomPxPerSec + 18)}" y="17" text-anchor="middle">HP</text></g>`
    : "";

  return `
    <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <path class="stem-overlay-line stem-overlay-line--${group}" d="${path}"></path>
      ${filterBadge}
    </svg>
  `;
}

function renderTimeline() {
  if (!currentSession || !timelineEl) return;
  const width = getTrackWidth();
  const interval = getRulerInterval();
  const totalDuration = currentSession.timing.total_duration;
  timelineEl.style.width = `${width}px`;
  timelineEl.innerHTML = "";

  for (let time = 0; time <= totalDuration + 0.001; time += interval) {
    const tick = document.createElement("div");
    tick.className = "stem-tick";
    tick.style.left = `${time * zoomPxPerSec}px`;
    if (Math.abs(time % Math.max(1, interval * 2)) < 0.001 || interval >= 1) {
      tick.classList.add("major");
    }

    const label = document.createElement("span");
    label.className = "stem-tick-label";
    label.textContent = interval < 1 ? `${time.toFixed(1)}s` : formatTime(time);
    tick.appendChild(label);
    timelineEl.appendChild(tick);
  }
}

function renderTransitionBand() {
  if (!currentSession || !transitionBandEl) return;
  const { song_a_exit_time, transition_end_time } = currentSession.timing;
  transitionBandEl.style.left = `${song_a_exit_time * zoomPxPerSec}px`;
  transitionBandEl.style.width = `${Math.max(4, (transition_end_time - song_a_exit_time) * zoomPxPerSec)}px`;
}

function renderStyleEnvelope(styleName = currentStyle) {
  if (!currentSession || !styleEnvelopeEl) return;
  const { song_a_exit_time, transition_end_time } = currentSession.timing;
  const startX = song_a_exit_time * zoomPxPerSec;
  const endX = transition_end_time * zoomPxPerSec;
  const width = Math.max(8, endX - startX);

  let topPolygon = `${startX},54 ${startX + width * 0.18},54 ${endX},10 ${endX},54`;
  let bottomPolygon = `${startX},10 ${startX},54 ${endX},54 ${endX - width * 0.18},10`;

  if (styleName === "Style_B") {
    topPolygon = `${startX},54 ${startX + width * 0.1},54 ${endX},26 ${endX},54`;
    bottomPolygon = `${startX},26 ${startX},54 ${endX},54 ${endX - width * 0.12},10`;
  } else if (styleName === "Style_C") {
    topPolygon = `${startX},54 ${startX + width * 0.12},54 ${startX + width * 0.52},16 ${endX},30 ${endX},54`;
    bottomPolygon = `${startX},18 ${startX},54 ${endX},54 ${endX - width * 0.14},10`;
  }

  styleEnvelopeEl.innerHTML = `
    <svg width="${getTrackWidth()}" height="56" viewBox="0 0 ${getTrackWidth()} 56" preserveAspectRatio="none">
      <polygon points="${topPolygon}" fill="rgba(255,123,123,0.22)"></polygon>
      <polygon points="${bottomPolygon}" fill="rgba(57,208,191,0.22)"></polygon>
    </svg>
  `;
}

function renderTrackOverlays(styleName = currentStyle) {
  const allTracks = [...TRACKS, ...MIX_TRACKS];
  allTracks.forEach(({ group, stem }) => {
    const overlay = document.getElementById(`overlay-${group.replace("_", "-")}-${stem}`);
    if (!overlay) return;
    overlay.innerHTML = buildOverlaySvg(group, stem === "mix" ? "other" : stem, styleName);
  });
}

function applyLayout() {
  const width = getTrackWidth();
  stageEl.style.width = `${width}px`;
  document.querySelectorAll(".stem-track-surface").forEach((el) => (el.style.width = `${width}px`));
  renderTimeline();
  renderTransitionBand();
  renderStyleEnvelope(currentStyle);
  renderTrackOverlays(currentStyle);
  syncScrollbarToViewport();
  updatePlayhead();
}

async function createWaveforms() {
  destroyWaveforms();
  waveformsReady = false;
  if (!currentSession) return;

  const width = getTrackWidth();
  for (const track of [...TRACKS, ...MIX_TRACKS]) {
    const container = document.getElementById(`waveform-${track.group.replace("_", "-")}-${track.stem}`);
    if (!container) continue;
    container.innerHTML = "";
    container.style.width = `${width}px`;

    const palette = track.stem === "mix"
      ? { wave: track.group === "song_a" ? "rgba(116, 224, 255, 0.30)" : "rgba(255, 175, 108, 0.30)", progress: track.group === "song_a" ? "rgba(116, 224, 255, 0.9)" : "rgba(255, 175, 108, 0.9)" }
      : COLORS[track.group][track.stem];
    const wave = WaveSurfer.create({
      container,
      waveColor: palette.wave,
      progressColor: palette.progress,
      cursorWidth: 0,
      interact: false,
      normalize: true,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: 72,
      minPxPerSec: zoomPxPerSec,
      autoScroll: false,
      fillParent: true,
      hideScrollbar: true,
    });
    waves[trackKey(track.group, track.stem)] = wave;
    await new Promise((resolve, reject) => {
      wave.once("ready", resolve);
      wave.once("error", reject);
      wave.load(currentSession.stems[track.group][track.stem]);
    });
  }
  waveformsReady = true;
}

function seekToClientX(clientX) {
  if (!currentSession || !viewportEl) return;
  const rect = viewportEl.getBoundingClientRect();
  const x = clientX - rect.left + viewportEl.scrollLeft;
  const time = pixelsToTime(x);
  if (masterAudio) {
    masterAudio.currentTime = time;
    updatePlayhead();
  }
}

function beginPlayheadDrag(pointerId) {
  resumePlaybackAfterDrag = Boolean(masterAudio && !masterAudio.paused);
  if (masterAudio && !masterAudio.paused) {
    masterAudio.pause();
  }
  isDraggingPlayhead = true;
  playheadPointerId = pointerId;
  viewportEl.classList.add("is-scrubbing");
  stopAnimatingPlayhead();
  debugLog("Playhead drag started. Playback paused for scrubbing.");
}

function endPlayheadDrag(pointerId = null) {
  if (!isDraggingPlayhead) return;
  if (pointerId !== null && playheadPointerId !== null && pointerId !== playheadPointerId) return;
  isDraggingPlayhead = false;
  playheadPointerId = null;
  viewportEl.classList.remove("is-scrubbing");
  if (masterAudio && resumePlaybackAfterDrag) {
    masterAudio.play().catch(() => {});
  }
  resumePlaybackAfterDrag = false;
  updatePlayhead();
  debugLog("Playhead drag ended.");
}

function animatePlayhead() {
  updatePlayhead();
  if (masterAudio && !masterAudio.paused) {
    animationFrameId = window.requestAnimationFrame(animatePlayhead);
  }
}

function stopAnimatingPlayhead() {
  if (animationFrameId) {
    window.cancelAnimationFrame(animationFrameId);
    animationFrameId = 0;
  }
}

function ensureMasterAudio() {
  if (masterAudio) return masterAudio;
  masterAudio = new Audio();
  masterAudio.preload = "auto";
  masterAudio.addEventListener("loadedmetadata", () => {
    totalTimeEl.textContent = formatTime(masterAudio.duration || currentSession?.timing.total_duration || 0);
    playButtonEl.disabled = false;
    updatePlayhead();
  });
  masterAudio.addEventListener("play", () => {
    playButtonEl.textContent = "Pause";
    stopAnimatingPlayhead();
    animatePlayhead();
  });
  masterAudio.addEventListener("pause", () => {
    playButtonEl.textContent = "Play";
    stopAnimatingPlayhead();
    updatePlayhead();
  });
  masterAudio.addEventListener("ended", () => {
    playButtonEl.textContent = "Play";
    stopAnimatingPlayhead();
    updatePlayhead();
  });
  return masterAudio;
}

async function loadMasterTransition(url) {
  const audio = ensureMasterAudio();
  if (audio.src !== url) {
    audio.src = url;
    audio.load();
  }
  currentRender = url;
  debugLog(`Loaded transition audio: ${url}`);
}

function updateWaveformZoom() {
  if (!waveformsReady) return;
  Object.values(waves).forEach((wave) => {
    wave.zoom(zoomPxPerSec);
  });
}

function updateGroupLayout() {
  ["song_a", "song_b"].forEach((group) => {
    const tracksStack = document.getElementById(`stem-${group.replace("_", "-")}-tracks`);
    const mixRow = document.getElementById(`stem-${group.replace("_", "-")}-mix-row`);
    const collapseButton = document.getElementById(`stem-collapse-${group === "song_a" ? "a" : "b"}`);
    const collapsed = groupCollapsed[group];
    tracksStack?.classList.toggle("hidden", collapsed);
    mixRow?.classList.toggle("hidden", !collapsed);
    if (collapseButton) collapseButton.textContent = collapsed ? "Expand" : "Collapse";
  });
}

function updateActiveStyleButton(styleName) {
  ["btn-style-a", "btn-style-b", "btn-style-c"].forEach((id) => {
    const button = document.getElementById(id);
    if (!button) return;
    button.classList.toggle(
      "active",
      (styleName === "Style_A" && id === "btn-style-a")
        || (styleName === "Style_B" && id === "btn-style-b")
        || (styleName === "Style_C" && id === "btn-style-c")
    );
  });
}

function chooseExistingStyle(styleName, gradual) {
  if (!currentSession?.existing_styles?.length) return null;
  const isGradualPath = (style) => style.saved_path.includes("/gradual_bpm/") || style.saved_path.includes("gradual_bpm/");
  return currentSession.existing_styles.find((style) => {
    return style.name === styleName && isGradualPath(style) === gradual;
  }) || null;
}

function attachStageListeners() {
  if (!viewportEl || viewportEl.dataset.bound === "true") return;
  viewportEl.dataset.bound = "true";

  viewportEl.addEventListener("scroll", () => {
    lastManualViewportInteractionAt = Date.now();
    syncScrollbarToViewport();
    currentTimeEl.textContent = formatTime(masterAudio ? masterAudio.currentTime : 0);
    playheadEl.style.left = `${timeToPixels(masterAudio ? masterAudio.currentTime : 0) - viewportEl.scrollLeft}px`;
  });

  viewportEl.addEventListener("click", (event) => {
    if (isDraggingPlayhead) return;
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (!target.closest(".stem-track-surface") && !target.closest(".stem-timeline-track")) return;
    seekToClientX(event.clientX);
    debugLog("Teleported playhead to clicked position.");
  });

  viewportEl.addEventListener("pointermove", (event) => {
    if (!isDraggingPlayhead) return;
    event.preventDefault();
    seekToClientX(event.clientX);
  });

  viewportEl.addEventListener("pointerup", (event) => {
    endPlayheadDrag(event.pointerId);
  });

  viewportEl.addEventListener("pointercancel", (event) => {
    endPlayheadDrag(event.pointerId);
  });

  playheadEl.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    event.stopPropagation();
    beginPlayheadDrag(event.pointerId);
    if (playheadEl.setPointerCapture) {
      playheadEl.setPointerCapture(event.pointerId);
    }
    seekToClientX(event.clientX);
  });

  playheadEl.addEventListener("pointerup", (event) => {
    endPlayheadDrag(event.pointerId);
  });

  playheadEl.addEventListener("pointercancel", (event) => {
    endPlayheadDrag(event.pointerId);
  });
}

function attachControlListeners() {
  if (scrollbarEl && !scrollbarEl.dataset.bound) {
    scrollbarEl.dataset.bound = "true";
    scrollbarEl.addEventListener("input", () => {
      lastManualViewportInteractionAt = Date.now();
      viewportEl.scrollLeft = Number(scrollbarEl.value);
      currentTimeEl.textContent = formatTime(masterAudio ? masterAudio.currentTime : 0);
      playheadEl.style.left = `${timeToPixels(masterAudio ? masterAudio.currentTime : 0) - viewportEl.scrollLeft}px`;
    });
  }

  if (playButtonEl && !playButtonEl.dataset.bound) {
    playButtonEl.dataset.bound = "true";
    playButtonEl.addEventListener("click", async () => {
      if (!masterAudio || !currentRender) return;
      if (masterAudio.paused) {
        await masterAudio.play();
      } else {
        masterAudio.pause();
      }
    });
  }

  if (zoomSliderEl && !zoomSliderEl.dataset.bound) {
    zoomSliderEl.dataset.bound = "true";
    zoomSliderEl.addEventListener("input", () => {
      zoomPxPerSec = Number(zoomSliderEl.value);
      if (!currentSession) return;
      updateWaveformZoom();
      applyLayout();
      if (masterAudio) {
        scrollViewportToPlayhead(timeToPixels(masterAudio.currentTime), true);
      }
      debugLog(`Zoom changed to ${zoomPxPerSec.toFixed(1)} px/sec.`);
    });
  }

  if (collapseAButton && !collapseAButton.dataset.bound) {
    collapseAButton.dataset.bound = "true";
    collapseAButton.addEventListener("click", () => {
      groupCollapsed.song_a = !groupCollapsed.song_a;
      updateGroupLayout();
    });
  }
  if (collapseBButton && !collapseBButton.dataset.bound) {
    collapseBButton.dataset.bound = "true";
    collapseBButton.addEventListener("click", () => {
      groupCollapsed.song_b = !groupCollapsed.song_b;
      updateGroupLayout();
    });
  }

  const zoomInButton = document.getElementById("stem-zoom-in");
  const zoomOutButton = document.getElementById("stem-zoom-out");
  if (zoomInButton && !zoomInButton.dataset.bound) {
    zoomInButton.dataset.bound = "true";
    zoomInButton.addEventListener("click", () => {
      zoomSliderEl.value = String(Math.min(240, Number(zoomSliderEl.value) + 20));
      zoomSliderEl.dispatchEvent(new Event("input"));
    });
  }
  if (zoomOutButton && !zoomOutButton.dataset.bound) {
    zoomOutButton.dataset.bound = "true";
    zoomOutButton.addEventListener("click", () => {
      zoomSliderEl.value = String(Math.max(40, Number(zoomSliderEl.value) - 20));
      zoomSliderEl.dispatchEvent(new Event("input"));
    });
  }
}

window.stemViz = {
  async loadSession(session, selectedSongs) {
    currentSession = {
      ...session,
      selectedSongs,
    };
    document.getElementById("stem-visualizer-area")?.classList.remove("hidden");
    document.getElementById("stem-session-label").textContent =
      `${selectedSongs.songA.title} -> ${selectedSongs.songB.title}`;
    groupTitleAEl.textContent = session.song_a_title || selectedSongs.songA.title;
    groupTitleBEl.textContent = session.song_b_title || selectedSongs.songB.title;
    totalTimeEl.textContent = formatTime(session.timing.total_duration);
    currentTimeEl.textContent = "0:00";
    playButtonEl.textContent = "Play";
    playButtonEl.disabled = true;
    currentStyle = "Style_A";
    currentRender = null;
    groupCollapsed.song_a = false;
    groupCollapsed.song_b = false;
    const fitZoom = getFitToScreenZoom();
    zoomSliderEl.min = String(fitZoom);
    zoomPxPerSec = Math.max(fitZoom, getDesiredInitialZoom());
    zoomSliderEl.value = String(zoomPxPerSec);

    attachStageListeners();
    attachControlListeners();
    debugLog("Creating waveform views for all stems...");
    await createWaveforms();
    applyLayout();
    updateGroupLayout();
    centerTransitionInView();
    setStyleButtonsDisabled(false);
    updateActiveStyleButton(currentStyle);
    debugLog(`Transition session loaded. Auto-zoom set to ${zoomPxPerSec.toFixed(1)} px/sec.`);

    const existingStyle = chooseExistingStyle("Style_A", false);
    if (existingStyle) {
      await loadMasterTransition(existingStyle.url);
      setStemStatus("Loaded aligned stems. Existing Style A render is ready to play.", "success");
    } else {
      setStemStatus("Aligned stems loaded. Pick a style to render the transition mix.", "success");
    }
  },

  async renderTransition(songAId, songBId, style, gradual, force = false) {
    setStemStatus(
      `${force ? "Re-rendering" : "Loading"} ${style.replace("_", " ")} (${gradual ? "gradual" : "constant"})...`,
      "loading"
    );
    setStyleButtonsDisabled(true);
    const startedAt = performance.now();
    debugLog(`Starting ${force ? "rerender" : "render load"} for ${style} (${gradual ? "gradual" : "constant"}).`);

    try {
      const response = await fetch("/api/stem_visualizer/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          song_a_id: songAId,
          song_b_id: songBId,
          style,
          gradual,
          force,
        }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }

      currentStyle = style;
      currentSession.existing_styles = payload.styles || currentSession.existing_styles || [];
      updateActiveStyleButton(style);
      renderStyleEnvelope(style);
      renderTrackOverlays(style);
      await loadMasterTransition(payload.url);
      debugLog(`Render request finished in ${((performance.now() - startedAt) / 1000).toFixed(2)}s.`);
      setStemStatus(`${payload.label} ready.`, "success");
    } catch (error) {
      debugLog(`Render failed: ${error.message}`);
      setStemStatus(`Render failed: ${error.message}`, "error");
    } finally {
      setStyleButtonsDisabled(false);
    }
  },
};
