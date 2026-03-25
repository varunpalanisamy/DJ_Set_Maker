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

let currentObjectUrl = null;
let currentPairs = [];
let activePairIndex = 0;

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) {
    return "0:00";
  }

  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function setStatus(message, type = "") {
  statusEl.textContent = message;
  statusEl.className = "status";
  if (type) {
    statusEl.classList.add(type);
  }
}

function setProcessingState(isProcessing) {
  submitButton.disabled = isProcessing;
  fileInput.disabled = isProcessing;
  submitButton.textContent = isProcessing ? "Processing..." : "Upload & Process";
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
    button.className = `style-chip${index === 0 ? " active" : ""}`;
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
    button.className = `pair-chip${index === activePairIndex ? " active" : ""}`;
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
    setStatus("Select one or more MP3 or WAV files first.", "error");
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

    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
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
    } else {
      const audioBlob = await response.blob();
      pairList.innerHTML = "";
      renderStyleButtons([]);
      attachProcessedAudio(audioBlob);
    }

    setStatus("Processing complete. Your DJ mixes are ready.", "success");
  } catch (error) {
    setStatus(`Processing failed: ${error.message}`, "error");
  } finally {
    setProcessingState(false);
  }
});
