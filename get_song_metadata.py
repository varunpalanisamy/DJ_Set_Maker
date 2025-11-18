import json
import math
from pathlib import Path

import librosa
import numpy as np
from mutagen import File as MutagenFile


def slugify(text: str) -> str:
    text = text.lower()
    for ch in [" ", "-", "(", ")", "[", "]", ",", ".", "!", "?"]:
        text = text.replace(ch, "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def parse_title_artist_from_filename(path: Path):
    """
    Try to parse 'Artist - Title.ext' from filename.
    If it fails, return (None, stem).
    """
    stem = path.stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return None, stem


def read_tags(path: Path):
    """
    Try to read metadata tags with mutagen.
    Returns (artist, title) or (None, None).
    """
    print(f"[read_tags] Trying to read tags from {path.name}...")
    try:
        audio = MutagenFile(path)
        if not audio or not audio.tags:
            print("[read_tags] No tags found.")
            return None, None

        artist = None
        title = None

        # ID3-style
        if "TPE1" in audio.tags:
            artist = str(audio.tags["TPE1"][0])
        if "TIT2" in audio.tags:
            title = str(audio.tags["TIT2"][0])

        # Fallback for other formats (e.g. VorbisComments)
        if not artist:
            for key in audio.tags.keys():
                if key.lower().startswith("artist"):
                    artist = str(audio.tags[key][0])
                    break

        if not title:
            for key in audio.tags.keys():
                if key.lower().startswith("title"):
                    title = str(audio.tags[key][0])
                    break

        print(f"[read_tags] Found tags -> artist={artist}, title={title}")
        return artist, title
    except Exception as e:
        print(f"[read_tags] Error reading tags: {e}")
        return None, None


# ------------------------------
# Audio feature extraction
# ------------------------------

def compute_loudness_db(y: np.ndarray) -> float:
    """
    Simple RMS-based loudness in dBFS.
    y should be mono float32 in [-1, 1].
    """
    rms = np.sqrt(np.mean(y ** 2) + 1e-12)
    loudness_db = 20 * math.log10(rms + 1e-12)
    return float(loudness_db)


def infer_energy_score(loudness_db: float) -> float:
    """
    Map loudness (roughly between -40 dB and 0 dB) to [0, 1].
    Clamped to that range.
    """
    min_db, max_db = -40.0, 0.0
    x = (loudness_db - min_db) / (max_db - min_db)
    x = max(0.0, min(1.0, x))
    return float(x)


def mood_from_energy(energy: float) -> str:
    if energy < 0.33:
        return "chill"
    elif energy < 0.66:
        return "medium"
    else:
        return "hype"


def detect_bpm_and_beats(y: np.ndarray, sr: int):
    """
    Returns (bpm, beat_times_list).
    """
    print("[detect_bpm_and_beats] Estimating tempo and beats...")
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

    # Make sure tempo is a plain float, not a numpy array
    tempo = float(tempo)

    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    print(f"[detect_bpm_and_beats] Estimated BPM: {tempo:.2f}, beats found: {len(beat_times)}")
    return float(tempo), beat_times.tolist()



def estimate_bars_from_beats(beat_times, beats_per_bar=4):
    """
    Very simple bar estimation: group beats into sets of N (e.g. 4/4).
    Returns list of bar start times.
    """
    bar_starts = []
    for i in range(0, len(beat_times), beats_per_bar):
        bar_starts.append(beat_times[i])
    print(f"[estimate_bars_from_beats] Estimated {len(bar_starts)} bars.")
    return bar_starts


# ------------------------------
# Key & Camelot
# ------------------------------

CAMELOT_MAP_MAJOR = {
    "C": "8B",
    "C#": "3B",
    "Db": "3B",
    "D": "10B",
    "D#": "5B",
    "Eb": "5B",
    "E": "12B",
    "F": "7B",
    "F#": "2B",
    "Gb": "2B",
    "G": "9B",
    "G#": "4B",
    "Ab": "4B",
    "A": "11B",
    "A#": "6B",
    "Bb": "6B",
    "B": "1B",
}

CAMELOT_MAP_MINOR = {
    "Cm": "5A",
    "C#m": "12A",
    "Dbm": "12A",
    "Dm": "7A",
    "D#m": "2A",
    "Ebm": "2A",
    "Em": "9A",
    "Fm": "4A",
    "F#m": "11A",
    "Gbm": "11A",
    "Gm": "6A",
    "G#m": "1A",
    "Abm": "1A",
    "Am": "8A",
    "A#m": "3A",
    "Bbm": "3A",
    "Bm": "10A",
}

PITCH_CLASS_NAMES = ["C", "C#", "D", "D#", "E", "F",
                     "F#", "G", "G#", "A", "A#", "B"]


def estimate_key_chroma(y: np.ndarray, sr: int):
    """
    Very rough key estimation using average chroma.
    Returns something like 'C#m' or 'G'.
    """
    print("[estimate_key_chroma] Estimating musical key...")
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = chroma.mean(axis=1)

    # Most prominent pitch class
    root_idx = int(np.argmax(chroma_mean))
    root_name = PITCH_CLASS_NAMES[root_idx]

    # Super crude major/minor guess:
    major_third_idx = (root_idx + 4) % 12
    minor_third_idx = (root_idx + 3) % 12
    if chroma_mean[minor_third_idx] > chroma_mean[major_third_idx]:
        key = f"{root_name}m"
    else:
        key = root_name

    print(f"[estimate_key_chroma] Estimated key: {key}")
    return key


def key_to_camelot(key: str):
    """
    Map key like 'C#m' or 'G' to Camelot notation if possible.
    """
    camelot = None
    if key.endswith("m"):  # minor
        camelot = CAMELOT_MAP_MINOR.get(key, None)
    else:
        camelot = CAMELOT_MAP_MAJOR.get(key, None)
    print(f"[key_to_camelot] Key {key} -> Camelot {camelot}")
    return camelot


# ------------------------------
# Main analysis function
# ------------------------------

def analyze_track(path_str: str):
    path = Path(path_str)
    print(f"\n=== Analyzing track: {path.name} ===")

    # ---------- Basic identity ----------
    print("[analyze_track] Reading tags / filename info...")
    artist_tag, title_tag = read_tags(path)
    artist_fn, title_fn = parse_title_artist_from_filename(path)

    artist = artist_tag or artist_fn or None
    title = title_tag or title_fn or path.stem

    if artist and title:
        track_id = slugify(f"{artist}_{title}")
    else:
        track_id = slugify(path.stem)

    print(f"[analyze_track] Identified -> track_id={track_id}, artist={artist}, title={title}")

    # ---------- Load audio ----------
    print("[analyze_track] Loading audio with librosa...")
    y, sr = librosa.load(path, sr=None, mono=True)
    duration_sec = float(librosa.get_duration(y=y, sr=sr))
    print(f"[analyze_track] Audio loaded: sr={sr}, duration={duration_sec:.2f} sec")

    # ---------- Loudness / energy ----------
    print("[analyze_track] Computing loudness and energy...")
    loudness_db = compute_loudness_db(y)
    energy_score = infer_energy_score(loudness_db)
    mood_tag = mood_from_energy(energy_score)
    print(f"[analyze_track] Loudness={loudness_db:.2f} dB, energy_score={energy_score:.3f}, mood={mood_tag}")

    # ---------- Tempo / beats / bars ----------
    bpm, beat_times = detect_bpm_and_beats(y, sr)
    bar_start_times = estimate_bars_from_beats(beat_times, beats_per_bar=4)

    # ---------- Key & Camelot ----------
    key = estimate_key_chroma(y, sr)
    camelot_key = key_to_camelot(key)

    # ---------- Build result ----------
    print("[analyze_track] Building final metadata dict...")
    result = {
        "track_id": track_id,
        "title": title,
        "artist": artist,
        "file_path": str(path.resolve()),
        "duration_sec": duration_sec,

        "bpm": bpm,
        "key": key,
        "camelot_key": camelot_key,

        "loudness_db": loudness_db,
        "energy_score": energy_score,
        "mood_tag": mood_tag,

        "beat_times": beat_times,
        "bar_start_times": bar_start_times,
    }

    print("[analyze_track] Done.")
    return result


# ------------------------------
# CLI entrypoint
# ------------------------------

if __name__ == "__main__":
    from pathlib import Path

    SONGS_DIR = Path("songs")
    METADATA_DIR = Path("metadata")
    AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}

    if not SONGS_DIR.exists():
        print(f"[main] songs/ folder not found at: {SONGS_DIR.resolve()}")
        raise SystemExit(1)

    METADATA_DIR.mkdir(exist_ok=True)
    print(f"[main] Scanning folder: {SONGS_DIR.resolve()}")
    print(f"[main] Metadata will be saved to: {METADATA_DIR.resolve()}")

    # Loop over all audio files in songs/
    count = 0
    for audio_path in sorted(SONGS_DIR.iterdir()):
        if audio_path.suffix.lower() not in AUDIO_EXTS:
            print(f"[main] Skipping non-audio file: {audio_path.name}")
            continue

        # Analyze this track
        meta = analyze_track(str(audio_path))

        # Save to metadata/<track_id>.json
        track_id = meta.get("track_id", "unknown_track")
        out_path = METADATA_DIR / f"{track_id}.json"

        with open(out_path, "w") as f:
            json.dump(meta, f, indent=2)

        print(f"[main] Saved metadata for {audio_path.name} -> {out_path.name}")
        count += 1

    print(f"\n[main] Done. Processed {count} audio file(s).")
