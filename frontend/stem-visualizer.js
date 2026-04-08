/**
 * Stem Visualizer — WaveSurfer.js v7 powered multi-stem view with synchronized scrolling.
 * Loaded as an ES module from index.html.
 */

import WaveSurfer from "https://cdn.jsdelivr.net/npm/wavesurfer.js@7/dist/wavesurfer.esm.js";
import TimelinePlugin from "https://cdn.jsdelivr.net/npm/wavesurfer.js@7/dist/plugins/timeline.esm.js";
import RegionsPlugin from "https://cdn.jsdelivr.net/npm/wavesurfer.js@7/dist/plugins/regions.esm.js";

const STEMS = ["vocals", "drums", "bass", "other"];
const PX_PER_SEC = 100;

const STEM_COLORS = {
  vocals: { wave: "rgba(139,245,220,0.55)", progress: "rgba(57,208,191,0.9)" },
  drums:  { wave: "rgba(243,177,90,0.55)",  progress: "rgba(220,130,30,0.9)" },
  bass:   { wave: "rgba(180,120,240,0.55)", progress: "rgba(150,70,230,0.9)" },
  other:  { wave: "rgba(100,185,255,0.55)", progress: "rgba(50,140,230,0.9)" },
};

let instances = {};      // { vocals: WaveSurfer, ... }
let transitionInfo = null;
let isSyncing = false;

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(sec) {
  if (!Number.isFinite(sec)) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function setStemStatus(msg, type = "") {
  const el = document.getElementById("stem-status");
  if (!el) return;
  el.textContent = msg;
  el.className = "status" + (type ? " " + type : "");
}

function setStyleButtonsDisabled(disabled) {
  ["btn-style-a", "btn-style-b", "btn-style-c"].forEach((id) => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = disabled;
  });
}

// ── Waveform lifecycle ────────────────────────────────────────────────────────

function destroyAll() {
  STEMS.forEach((stem) => {
    instances[stem]?.destroy();
    instances[stem] = null;
  });
}

// ── Scroll synchronisation ───────────────────────────────────────────────────

function syncScrollFromSource(sourceWrapper) {
  if (isSyncing) return;
  isSyncing = true;
  const max = sourceWrapper.scrollWidth - sourceWrapper.clientWidth;
  const ratio = max > 0 ? sourceWrapper.scrollLeft / max : 0;

  STEMS.forEach((stem) => {
    const w = instances[stem]?.getWrapper();
    if (!w || w === sourceWrapper) return;
    const m = w.scrollWidth - w.clientWidth;
    w.scrollLeft = ratio * m;
  });

  // Keep shared scrollbar in sync
  const scrollbar = document.getElementById("stem-scrollbar");
  if (scrollbar) {
    const sbMax = parseFloat(scrollbar.max) || 0;
    scrollbar.value = String(ratio * sbMax);
  }

  // Update transition marker position in timeline bar
  updateTimelineMarker();

  isSyncing = false;
}

// ── Timeline bar marker ───────────────────────────────────────────────────────

function updateTimelineMarker() {
  if (!transitionInfo || !instances.vocals) return;

  const ws = instances.vocals;
  const wrapper = ws.getWrapper();
  if (!wrapper) return;

  const scrollLeft = wrapper.scrollLeft;
  const clientWidth = wrapper.clientWidth;
  const totalDur = ws.getDuration();
  if (!totalDur) return;

  const visStart = scrollLeft / PX_PER_SEC;
  const visEnd = (scrollLeft + clientWidth) / PX_PER_SEC;

  const markerEl = document.getElementById("stem-transition-marker");
  if (!markerEl) return;

  const exitTime = transitionInfo.song_a_exit_time;

  if (exitTime >= visStart && exitTime <= visEnd) {
    const ratio = (exitTime - visStart) / (visEnd - visStart);
    const timelineCol = document.getElementById("timeline-container");
    const colWidth = timelineCol ? timelineCol.clientWidth : clientWidth;
    markerEl.style.left = `${ratio * colWidth}px`;
    markerEl.style.display = "block";
    markerEl.title = `Transition at ${formatTime(exitTime)}`;
  } else {
    markerEl.style.display = "none";
  }
}

// ── Playback synchronisation ──────────────────────────────────────────────────

function attachPlaybackSync(stem, ws) {
  ws.on("seeking", (time) => {
    if (isSyncing) return;
    isSyncing = true;
    STEMS.forEach((s) => {
      if (s !== stem && instances[s]) instances[s].setTime(time);
    });
    isSyncing = false;
  });

  ws.on("play", () => {
    if (isSyncing) return;
    isSyncing = true;
    STEMS.forEach((s) => {
      if (s !== stem && instances[s] && !instances[s].isPlaying()) {
        instances[s].play();
      }
    });
    const btn = document.getElementById("stem-play-btn");
    if (btn) btn.textContent = "Pause";
    isSyncing = false;
  });

  ws.on("pause", () => {
    if (isSyncing) return;
    isSyncing = true;
    STEMS.forEach((s) => {
      if (s !== stem && instances[s] && instances[s].isPlaying()) {
        instances[s].pause();
      }
    });
    const btn = document.getElementById("stem-play-btn");
    if (btn) btn.textContent = "Play";
    isSyncing = false;
  });

  ws.on("finish", () => {
    const btn = document.getElementById("stem-play-btn");
    if (btn) btn.textContent = "Play";
  });

  if (stem === "vocals") {
    ws.on("timeupdate", (time) => {
      const el = document.getElementById("stem-current-time");
      if (el) el.textContent = formatTime(time);
    });
  }
}

// ── Region markers ────────────────────────────────────────────────────────────

function addTransitionRegions(regions, stem) {
  if (!transitionInfo) return;

  const { song_a_exit_time, song_a_duration, song_b_entry_in_combined } = transitionInfo;
  const isFirst = stem === "vocals";

  // Song A exit / transition start — thin red line
  regions.addRegion({
    start: song_a_exit_time,
    end: song_a_exit_time + 0.15,
    color: "rgba(255,80,60,0.35)",
    drag: false,
    resize: false,
    content: isFirst ? `⚡ ${formatTime(song_a_exit_time)}` : undefined,
  });

  // Song A / Song B hard boundary — thin white line
  regions.addRegion({
    start: song_a_duration - 0.08,
    end: song_a_duration + 0.08,
    color: "rgba(255,255,255,0.18)",
    drag: false,
    resize: false,
    content: isFirst ? "| B" : undefined,
  });

  // Song B entry point — thin teal line
  regions.addRegion({
    start: song_b_entry_in_combined,
    end: song_b_entry_in_combined + 0.15,
    color: "rgba(57,208,191,0.35)",
    drag: false,
    resize: false,
    content: isFirst ? `🎵 ${formatTime(song_b_entry_in_combined)}` : undefined,
  });
}

// ── Main init ─────────────────────────────────────────────────────────────────

async function initWaveforms(stemUrls) {
  destroyAll();

  const readyPromises = STEMS.map((stem, idx) => {
    return new Promise((resolve) => {
      const container = document.getElementById(`waveform-${stem}`);
      const plugins = [];

      // Timeline only on the vocals (first) track; container is the shared timeline bar
      if (idx === 0) {
        plugins.push(
          TimelinePlugin.create({
            container: "#timeline-container",
            height: 24,
            timeInterval: 10,
            primaryLabelInterval: 60,
            secondaryLabelInterval: 30,
            style: {
              fontSize: "10px",
              color: "#93a4bb",
              fontFamily: "'Avenir Next', 'Helvetica Neue', sans-serif",
            },
          })
        );
      }

      const regionsPlugin = RegionsPlugin.create();
      plugins.push(regionsPlugin);

      const ws = WaveSurfer.create({
        container,
        waveColor: STEM_COLORS[stem].wave,
        progressColor: STEM_COLORS[stem].progress,
        cursorColor: "rgba(255,255,255,0.5)",
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        height: 72,
        minPxPerSec: PX_PER_SEC,
        scrollParent: true,
        normalize: true,
        plugins,
      });

      instances[stem] = ws;

      // Hide the native scrollbar on the waveform wrapper
      ws.once("ready", () => {
        const wrapper = ws.getWrapper();
        wrapper.style.scrollbarWidth = "none";
        wrapper.style.msOverflowStyle = "none";

        addTransitionRegions(regionsPlugin, stem);

        if (stem === "vocals") {
          const dur = ws.getDuration();
          const totalEl = document.getElementById("stem-total-time");
          if (totalEl) totalEl.textContent = formatTime(dur);

          // Set shared scrollbar range
          const scrollbar = document.getElementById("stem-scrollbar");
          if (scrollbar) {
            const maxScroll = wrapper.scrollWidth - wrapper.clientWidth;
            scrollbar.max = String(Math.max(maxScroll, 1));
            scrollbar.value = "0";
          }

          updateTimelineMarker();
        }

        // Scroll sync
        ws.getWrapper().addEventListener("scroll", () => {
          syncScrollFromSource(ws.getWrapper());
        });

        attachPlaybackSync(stem, ws);
        resolve();
      });

      ws.load(stemUrls[stem]);
    });
  });

  await Promise.all(readyPromises);

  // Shared scrollbar
  const scrollbar = document.getElementById("stem-scrollbar");
  if (scrollbar) {
    scrollbar.addEventListener("input", () => {
      if (isSyncing) return;
      isSyncing = true;
      const val = parseFloat(scrollbar.value);
      STEMS.forEach((stem) => {
        const w = instances[stem]?.getWrapper();
        if (w) w.scrollLeft = val;
      });
      updateTimelineMarker();
      isSyncing = false;
    });
  }

  // Play button
  const playBtn = document.getElementById("stem-play-btn");
  if (playBtn) {
    // Remove old listeners by cloning
    const freshBtn = playBtn.cloneNode(true);
    playBtn.parentNode.replaceChild(freshBtn, playBtn);
    freshBtn.addEventListener("click", () => {
      const vocals = instances.vocals;
      if (!vocals) return;
      if (vocals.isPlaying()) {
        STEMS.forEach((s) => instances[s]?.pause());
        freshBtn.textContent = "Play";
      } else {
        STEMS.forEach((s) => instances[s]?.play());
        freshBtn.textContent = "Pause";
      }
    });
  }
}

// ── Public API (attached to window) ──────────────────────────────────────────

window.stemViz = {
  async prepare(songAId, songBId) {
    setStemStatus("Preparing stems… (may take a while if Demucs needs to run)", "loading");
    document.getElementById("stem-visualizer-area")?.classList.add("hidden");

    try {
      const res = await fetch("/api/stem_visualizer/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ song_a_id: songAId, song_b_id: songBId }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }

      transitionInfo = await res.json();
      await initWaveforms(transitionInfo.stems);

      document.getElementById("stem-visualizer-area")?.classList.remove("hidden");
      setStemStatus(
        `Stems loaded. Transition at ${formatTime(transitionInfo.song_a_exit_time)}. Click a style to render.`,
        "success"
      );
    } catch (err) {
      setStemStatus(`Error: ${err.message}`, "error");
    }
  },

  async renderTransition(songAId, songBId, style, gradual) {
    setStemStatus(
      `Rendering ${style.replace("_", " ")} (${gradual ? "gradual" : "constant"} BPM)…`,
      "loading"
    );
    setStyleButtonsDisabled(true);

    try {
      const res = await fetch("/api/stem_visualizer/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ song_a_id: songAId, song_b_id: songBId, style, gradual }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }

      const result = await res.json();
      setStemStatus(`✓ ${result.label} ready.`, "success");
      window.dispatchEvent(new CustomEvent("stemTransitionReady", { detail: result }));
    } catch (err) {
      setStemStatus(`Render failed: ${err.message}`, "error");
    } finally {
      const hasBoth = !!(window.stemSongA && window.stemSongB);
      setStyleButtonsDisabled(!hasBoth);
    }
  },
};
