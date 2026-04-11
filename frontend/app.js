const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("audio-file");
const fileName = document.getElementById("file-name");
const submitButton = document.getElementById("submit-button");
const statusEl = document.getElementById("status");
const playerSection = document.getElementById("player-section");
const audioPlayer = document.getElementById("audio-player");
const playToggle = document.getElementById("play-toggle");
const timeline = document.getElementById("timeline");
const currentTimeEl = document.getElementById("current-time");
const totalTimeEl = document.getElementById("total-time");
const pairName = document.getElementById("pair-name");
const resultPath = document.getElementById("result-path");
const pairList = document.getElementById("pair-list");
const styleList = document.getElementById("style-list");

const tabButtons = document.querySelectorAll(".nav-tab");
const downloadView = document.getElementById("download-view");
const pitchView = document.getElementById("pitch-view");
const stemView = document.getElementById("stem-view");

const songAList = document.getElementById("song-a-list");
const songBList = document.getElementById("song-b-list");
const songASelected = document.getElementById("song-a-selected");
const songBSelected = document.getElementById("song-b-selected");
const compareButton = document.getElementById("compare-button");
const compareStatus = document.getElementById("compare-status");
const resultsCard = document.getElementById("results-card");
const totalScoreEl = document.getElementById("total-score");
const dominantFlag = document.getElementById("dominant-flag");
const doubletimeFlag = document.getElementById("doubletime-flag");
const resultsExplanation = document.getElementById("results-explanation");
const tempoScore = document.getElementById("tempo-score");
const tempoDetail = document.getElementById("tempo-detail");
const harmonicScore = document.getElementById("harmonic-score");
const harmonicDetail = document.getElementById("harmonic-detail");
const harmonicFix = document.getElementById("harmonic-fix");
const harmonicShiftBadge = document.getElementById("harmonic-shift-badge");
const harmonicShiftDetail = document.getElementById("harmonic-shift-detail");
const textureScore = document.getElementById("texture-score");
const textureDetail = document.getElementById("texture-detail");

let currentObjectUrl = null;
let currentPairs = [];
let activePairIndex = 0;
let librarySongs = [];
let selectedSongA = null;
let selectedSongB = null;

// Stem Visualizer state
let stemSelectedA = null;
let stemSelectedB = null;
window.stemSongA = null;
window.stemSongB = null;

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) {
    return "0:00";
  }

  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function formatSongLabel(song) {
  return `${song.title} - ${song.artist}`;
}

function setStatus(message, type = "") {
  statusEl.textContent = message;
  statusEl.className = "status";
  if (type) {
    statusEl.classList.add(type);
  }
}

function setCompareStatus(message, type = "") {
  compareStatus.textContent = message;
  compareStatus.className = "status";
  if (type) {
    compareStatus.classList.add(type);
  }
}

function setProcessingState(isProcessing) {
  submitButton.disabled = isProcessing;
  fileInput.disabled = isProcessing;
  submitButton.textContent = isProcessing ? "Processing..." : "Upload & Process";
}

function setCompareState(isProcessing) {
  compareButton.disabled = isProcessing || !selectedSongA || !selectedSongB;
  compareButton.textContent = isProcessing ? "Comparing..." : "Compare";
}

function attachProcessedAudio(source, savedPath = "", currentPairLabel = "") {
  if (currentObjectUrl) {
    URL.revokeObjectURL(currentObjectUrl);
    currentObjectUrl = null;
  }

  if (source instanceof Blob) {
    currentObjectUrl = URL.createObjectURL(source);
    audioPlayer.src = currentObjectUrl;
  } else {
    audioPlayer.src = source;
  }

  audioPlayer.load();
  playerSection.classList.remove("hidden");
  playToggle.textContent = "Play";
  timeline.value = 0;
  currentTimeEl.textContent = "0:00";
  pairName.textContent = currentPairLabel;
  resultPath.textContent = savedPath ? `Saved to ${savedPath}` : "";
}

function renderStyleButtons(styles, pairLabel) {
  styleList.innerHTML = "";

  styles.forEach((style, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chip style-chip${index === 0 ? " active" : ""}`;
    button.textContent = style.label || style.name;
    button.addEventListener("click", () => {
      document.querySelectorAll(".style-chip").forEach((chip) => chip.classList.remove("active"));
      button.classList.add("active");
      attachProcessedAudio(style.url, style.saved_path || "", pairLabel);
    });
    styleList.appendChild(button);
  });
}

function renderPairButtons(pairs) {
  pairList.innerHTML = "";
  currentPairs = pairs;

  pairs.forEach((pair, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chip pair-chip${index === activePairIndex ? " active" : ""}`;
    button.textContent = pair.label;
    button.addEventListener("click", () => {
      activePairIndex = index;
      document.querySelectorAll(".pair-chip").forEach((chip) => chip.classList.remove("active"));
      button.classList.add("active");
      renderSelectedPair();
    });
    pairList.appendChild(button);
  });
}

function renderSelectedPair() {
  const pair = currentPairs[activePairIndex];
  if (!pair || !pair.styles || pair.styles.length === 0) {
    return;
  }

  renderStyleButtons(pair.styles, pair.label);
  attachProcessedAudio(pair.styles[0].url, pair.styles[0].saved_path || "", pair.label);
}

function switchView(viewName) {
  tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewName);
  });
  downloadView.classList.toggle("hidden", viewName !== "download");
  pitchView.classList.toggle("hidden", viewName !== "pitch");
  stemView.classList.toggle("hidden", viewName !== "stem");
}

function renderSongList(targetEl, songs, selectedId, onSelect) {
  targetEl.innerHTML = "";
  songs.forEach((song) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `song-row${selectedId === song.track_id ? " active" : ""}`;
    button.innerHTML = `
      <span class="song-title">${song.title}</span>
      <span class="song-subline">
        <span class="song-pill"><strong>Key:</strong> ${song.key}</span>
        <span class="song-pill"><strong>Camelot:</strong> ${song.camelot_key}</span>
      </span>
    `;
    button.addEventListener("click", () => onSelect(song));
    targetEl.appendChild(button);
  });
}

function renderMatcherSelections() {
  renderSongList(songAList, librarySongs, selectedSongA?.track_id, (song) => {
    selectedSongA = song;
    songASelected.textContent = formatSongLabel(song);
    renderMatcherSelections();
  });

  renderSongList(songBList, librarySongs, selectedSongB?.track_id, (song) => {
    selectedSongB = song;
    songBSelected.textContent = formatSongLabel(song);
    renderMatcherSelections();
  });

  if (!selectedSongA) {
    songASelected.textContent = "No song selected";
  }
  if (!selectedSongB) {
    songBSelected.textContent = "No song selected";
  }
  setCompareState(false);
}

async function loadSongs() {
  setCompareStatus("Loading song library...", "loading");
  try {
    const response = await fetch("/api/songs");
    if (!response.ok) {
      throw new Error(`Song library request failed with status ${response.status}`);
    }
    librarySongs = await response.json();
    renderMatcherSelections();
    renderStemSelections();
    setCompareStatus(`Loaded ${librarySongs.length} analyzed song(s).`, "success");
  } catch (error) {
    setCompareStatus(`Could not load songs: ${error.message}`, "error");
  }
}

function renderComparisonResult(payload) {
  resultsCard.classList.remove("hidden");
  totalScoreEl.textContent = `${Math.round(payload.total_score)}%`;
  resultsExplanation.textContent = payload.explanation || "";

  dominantFlag.classList.toggle("hidden", !payload.is_dominant_tonic);
  doubletimeFlag.classList.toggle("hidden", !payload.is_double_time);

  tempoScore.textContent = `${Math.round(payload.breakdown.tempo.score)}`;
  tempoDetail.textContent =
    `${payload.breakdown.tempo.mode.replace("_", " ")} • gap ${payload.breakdown.tempo.effective_gap_percent}%`;

  harmonicScore.textContent = `${Math.round(payload.breakdown.harmonic.score)}`;
  harmonicDetail.textContent = payload.breakdown.harmonic.label;
  if (payload.suggested_shift !== 0) {
    const shiftPrefix = payload.suggested_shift > 0 ? "+" : "";
    harmonicFix.classList.remove("hidden");
    harmonicShiftBadge.textContent = `Suggested Shift: ${shiftPrefix}${payload.suggested_shift} Semitones`;
    harmonicShiftDetail.textContent = payload.shift_label || "";
  } else {
    harmonicFix.classList.add("hidden");
    harmonicShiftBadge.textContent = "";
    harmonicShiftDetail.textContent = "";
  }

  textureScore.textContent = `${Math.round(payload.breakdown.texture.score)}`;
  textureDetail.textContent =
    `Contrast ${payload.breakdown.texture.contrast_similarity}, onset ${payload.breakdown.texture.onset_similarity}`;
}

tabButtons.forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

fileInput.addEventListener("change", () => {
  const selectedFiles = Array.from(fileInput.files || []);
  if (selectedFiles.length === 0) {
    fileName.textContent = "No file selected";
  } else if (selectedFiles.length === 1) {
    fileName.textContent = selectedFiles[0].name;
  } else {
    fileName.textContent = `${selectedFiles.length} files selected`;
  }
});

playToggle.addEventListener("click", async () => {
  if (!audioPlayer.src) {
    return;
  }

  if (audioPlayer.paused) {
    await audioPlayer.play();
    playToggle.textContent = "Pause";
  } else {
    audioPlayer.pause();
    playToggle.textContent = "Play";
  }
});

audioPlayer.addEventListener("loadedmetadata", () => {
  timeline.max = audioPlayer.duration || 0;
  totalTimeEl.textContent = formatTime(audioPlayer.duration);
});

audioPlayer.addEventListener("timeupdate", () => {
  timeline.value = audioPlayer.currentTime;
  currentTimeEl.textContent = formatTime(audioPlayer.currentTime);
});

audioPlayer.addEventListener("ended", () => {
  playToggle.textContent = "Play";
});

timeline.addEventListener("input", () => {
  audioPlayer.currentTime = Number(timeline.value);
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const selectedFiles = Array.from(fileInput.files || []);
  if (selectedFiles.length === 0) {
    setStatus("Select one or more supported audio files first.", "error");
    return;
  }

  const formData = new FormData();
  selectedFiles.forEach((file) => {
    formData.append("files", file);
  });

  setProcessingState(true);
  setStatus(`Processing ${selectedFiles.length} file(s)...`, "loading");
  playerSection.classList.add("hidden");

  try {
    const response = await fetch("/process", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    const payload = await response.json();
    if (!payload.url && (!payload.pairs || payload.pairs.length === 0)) {
      throw new Error("Backend response did not include any playable output.");
    }

    if (payload.pairs && payload.pairs.length > 0) {
      activePairIndex = 0;
      renderPairButtons(payload.pairs);
      renderSelectedPair();
    } else {
      pairList.innerHTML = "";
      renderStyleButtons([]);
      attachProcessedAudio(payload.url, payload.saved_path || "", payload.pair_label || "");
    }

    setStatus("Processing complete. Your DJ mixes are ready.", "success");
    loadSongs();
  } catch (error) {
    setStatus(`Processing failed: ${error.message}`, "error");
  } finally {
    setProcessingState(false);
  }
});

compareButton.addEventListener("click", async () => {
  if (!selectedSongA || !selectedSongB) {
    return;
  }

  setCompareState(true);
  setCompareStatus("Running compatibility analysis...", "loading");
  resultsCard.classList.add("hidden");

  try {
    const response = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        song_a_id: selectedSongA.track_id,
        song_b_id: selectedSongB.track_id,
      }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Comparison failed with status ${response.status}`);
    }

    renderComparisonResult(payload);
    setCompareStatus("Comparison complete.", "success");
  } catch (error) {
    setCompareStatus(`Comparison failed: ${error.message}`, "error");
  } finally {
    setCompareState(false);
  }
});

// ── Stem Visualizer ──────────────────────────────────────────────────────────

const stemSongAList = document.getElementById("stem-song-a-list");
const stemSongBList = document.getElementById("stem-song-b-list");
const stemSongASelected = document.getElementById("stem-song-a-selected");
const stemSongBSelected = document.getElementById("stem-song-b-selected");
const gradualToggle = document.getElementById("gradual-toggle");
const btnStyleA = document.getElementById("btn-style-a");
const btnStyleB = document.getElementById("btn-style-b");
const btnStyleC = document.getElementById("btn-style-c");
const stemOpenPickerButton = document.getElementById("stem-open-picker");
const stemPickerModal = document.getElementById("stem-picker-modal");
const stemPickerConfirm = document.getElementById("stem-picker-confirm");
const stemPickerCancel = document.getElementById("stem-picker-cancel");
const stemPickerCancelTop = document.getElementById("stem-picker-cancel-top");
const stemRerenderModal = document.getElementById("stem-rerender-modal");
const stemRerenderYes = document.getElementById("stem-rerender-yes");
const stemRerenderNo = document.getElementById("stem-rerender-no");
const stemDebugLog = document.getElementById("stem-debug-log");
const stemDebugClear = document.getElementById("stem-debug-clear");
let pendingStemSession = null;

function appendStemDebug(message) {
  if (!stemDebugLog) return;
  const entry = document.createElement("div");
  entry.className = "stem-debug-entry";
  const time = new Date().toLocaleTimeString();
  entry.textContent = `[${time}] ${message}`;
  stemDebugLog.prepend(entry);
}

window.appendStemDebug = appendStemDebug;

function updateStemControls() {
  const hasBoth = !!(stemSelectedA && stemSelectedB);
  stemPickerConfirm.disabled = !hasBoth;
  btnStyleA.disabled = !hasBoth;
  btnStyleB.disabled = !hasBoth;
  btnStyleC.disabled = !hasBoth;
}

function renderStemSelections() {
  renderSongList(stemSongAList, librarySongs, stemSelectedA?.track_id, (song) => {
    stemSelectedA = song;
    window.stemSongA = song;
    stemSongASelected.textContent = formatSongLabel(song);
    renderStemSelections();
  });

  renderSongList(stemSongBList, librarySongs, stemSelectedB?.track_id, (song) => {
    stemSelectedB = song;
    window.stemSongB = song;
    stemSongBSelected.textContent = formatSongLabel(song);
    renderStemSelections();
  });

  if (!stemSelectedA) stemSongASelected.textContent = "No song selected";
  if (!stemSelectedB) stemSongBSelected.textContent = "No song selected";
  updateStemControls();
}

function toggleModal(modal, isOpen) {
  modal.classList.toggle("hidden", !isOpen);
  modal.setAttribute("aria-hidden", String(!isOpen));
}

function openStemPicker() {
  toggleModal(stemPickerModal, true);
}

function closeStemPicker() {
  toggleModal(stemPickerModal, false);
}

function closeStemRerenderModal() {
  toggleModal(stemRerenderModal, false);
}

async function handleStemCreate() {
  if (!stemSelectedA || !stemSelectedB) return;
  closeStemPicker();

  try {
    appendStemDebug(`Create Transition clicked for ${stemSelectedA.track_id} -> ${stemSelectedB.track_id}`);
    const startedAt = performance.now();
    const response = await fetch("/api/stem_visualizer/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        song_a_id: stemSelectedA.track_id,
        song_b_id: stemSelectedB.track_id,
      }),
    });
    const session = await response.json();
    appendStemDebug(`Prepare request finished in ${((performance.now() - startedAt) / 1000).toFixed(2)}s`);
    if (!response.ok) {
      throw new Error(session.error || `HTTP ${response.status}`);
    }

    pendingStemSession = {
      session,
      selectedSongs: {
        songA: stemSelectedA,
        songB: stemSelectedB,
      },
    };

    if (session.has_existing_transition) {
      appendStemDebug("Existing rendered transition found. Asking whether to reuse or rerender.");
      toggleModal(stemRerenderModal, true);
      return;
    }

    appendStemDebug("No existing render found. Loading session and rendering Style A.");
    await window.stemViz.loadSession(session, {
      songA: stemSelectedA,
      songB: stemSelectedB,
    });

    await window.stemViz.renderTransition(
      stemSelectedA.track_id,
      stemSelectedB.track_id,
      "Style_A",
      gradualToggle ? gradualToggle.checked : false,
      true
    );
  } catch (error) {
    appendStemDebug(`Create Transition failed: ${error.message}`);
    const stemStatus = document.getElementById("stem-status");
    if (stemStatus) {
      stemStatus.textContent = `Could not open transition session: ${error.message}`;
      stemStatus.className = "status error";
    }
  }
}

function makeStemStyleHandler(styleName) {
  return async () => {
    if (!stemSelectedA || !stemSelectedB) return;
    const gradual = gradualToggle ? gradualToggle.checked : false;
    [btnStyleA, btnStyleB, btnStyleC].forEach((b) => b.classList.remove("active"));
    const activeBtn = { Style_A: btnStyleA, Style_B: btnStyleB, Style_C: btnStyleC }[styleName];
    activeBtn?.classList.add("active");
    if (window.stemViz) {
      await window.stemViz.renderTransition(
        stemSelectedA.track_id,
        stemSelectedB.track_id,
        styleName,
        gradual
      );
    }
  };
}

btnStyleA.addEventListener("click", makeStemStyleHandler("Style_A"));
btnStyleB.addEventListener("click", makeStemStyleHandler("Style_B"));
btnStyleC.addEventListener("click", makeStemStyleHandler("Style_C"));
stemOpenPickerButton.addEventListener("click", openStemPicker);
stemPickerConfirm.addEventListener("click", handleStemCreate);
stemPickerCancel.addEventListener("click", closeStemPicker);
stemPickerCancelTop.addEventListener("click", closeStemPicker);
stemRerenderYes.addEventListener("click", async () => {
  closeStemRerenderModal();
  if (!pendingStemSession) return;
  appendStemDebug("User chose to rerender the transition.");
  await window.stemViz.loadSession(pendingStemSession.session, pendingStemSession.selectedSongs);
  await window.stemViz.renderTransition(
    stemSelectedA.track_id,
    stemSelectedB.track_id,
    "Style_A",
    gradualToggle ? gradualToggle.checked : false,
    true
  );
  pendingStemSession = null;
});
stemRerenderNo.addEventListener("click", () => {
  closeStemRerenderModal();
  if (!pendingStemSession) return;
  appendStemDebug("User chose to reuse the existing transition.");
  window.stemViz.loadSession(pendingStemSession.session, pendingStemSession.selectedSongs);
  pendingStemSession = null;
});
stemDebugClear.addEventListener("click", () => {
  stemDebugLog.innerHTML = "";
});

switchView("download");
loadSongs();
