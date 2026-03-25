import json
import math
import warnings
from pathlib import Path

# This hides the "FutureWarning" noise from the terminal
warnings.filterwarnings("ignore", category=FutureWarning)

import allin1
import librosa
import numpy as np
from mutagen import File as MutagenFile


PROJECT_ROOT = Path(__file__).resolve().parent
SONGS_DIR = PROJECT_ROOT / "songs"
METADATA_DIR = PROJECT_ROOT / "metadata"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}

def slugify(text: str) -> str:
    text = text.lower()
    for ch in [" ", "-", "(", ")", "[", "]", ",", ".", "!", "?"]:
        text = text.replace(ch, "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")

def parse_title_artist_from_filename(path: Path):
    stem = path.stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return None, stem

def read_tags(path: Path):
    try:
        audio = MutagenFile(path)
        if not audio or not audio.tags:
            return None, None
        artist, title = None, None
        if "TPE1" in audio.tags: artist = str(audio.tags["TPE1"][0])
        if "TIT2" in audio.tags: title = str(audio.tags["TIT2"][0])
        return artist, title
    except Exception:
        return None, None

def get_closest_beat(target_time, beat_times):
    if not beat_times:
        return 0, target_time
    idx = min(range(len(beat_times)), key=lambda i: abs(beat_times[i] - target_time))
    return idx, beat_times[idx]

def compute_loudness_db(y: np.ndarray) -> float:
    rms = np.sqrt(np.mean(y ** 2) + 1e-12)
    return float(20 * math.log10(rms + 1e-12))

def infer_energy_score(loudness_db: float) -> float:
    min_db, max_db = -40.0, 0.0
    x = (loudness_db - min_db) / (max_db - min_db)
    return float(max(0.0, min(1.0, x)))

def mood_from_energy(energy: float) -> str:
    if energy < 0.33: return "chill"
    elif energy < 0.66: return "medium"
    else: return "hype"

def estimate_bars_from_beats(beat_times, beats_per_bar=4):
    return [beat_times[i] for i in range(0, len(beat_times), beats_per_bar)]

def estimate_key_chroma(y: np.ndarray, sr: int):
    PITCH_CLASS_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = chroma.mean(axis=1)
    root_idx = int(np.argmax(chroma_mean))
    root_name = PITCH_CLASS_NAMES[root_idx]
    major_third_idx = (root_idx + 4) % 12
    minor_third_idx = (root_idx + 3) % 12
    key = f"{root_name}m" if chroma_mean[minor_third_idx] > chroma_mean[major_third_idx] else root_name
    return key

def key_to_camelot(key: str):
    CAMELOT_MAP_MAJOR = {"C": "8B", "C#": "3B", "Db": "3B", "D": "10B", "D#": "5B", "Eb": "5B", "E": "12B", "F": "7B", "F#": "2B", "Gb": "2B", "G": "9B", "G#": "4B", "Ab": "4B", "A": "11B", "A#": "6B", "Bb": "6B", "B": "1B"}
    CAMELOT_MAP_MINOR = {"Cm": "5A", "C#m": "12A", "Dbm": "12A", "Dm": "7A", "D#m": "2A", "Ebm": "2A", "Em": "9A", "Fm": "4A", "F#m": "11A", "Gbm": "11A", "Gm": "6A", "G#m": "1A", "Abm": "1A", "Am": "8A", "A#m": "3A", "Bbm": "3A", "Bm": "10A"}
    if key.endswith("m"): return CAMELOT_MAP_MINOR.get(key, None)
    return CAMELOT_MAP_MAJOR.get(key, None)

# ------------------------------
# Main Analysis
# ------------------------------

def analyze_track(path_str: str):
    path = Path(path_str)
    print(f"\n=== Analyzing track: {path.name} ===")

    artist_tag, title_tag = read_tags(path)
    artist_fn, title_fn = parse_title_artist_from_filename(path)
    artist = artist_tag or artist_fn or "Unknown Artist"
    title = title_tag or title_fn or path.stem
    track_id = slugify(f"{artist}_{title}")

    y, sr = librosa.load(path, sr=None, mono=True)
    duration_sec = float(librosa.get_duration(y=y, sr=sr))

    loudness_db = compute_loudness_db(y)
    energy_score = infer_energy_score(loudness_db)
    mood_tag = mood_from_energy(energy_score)
    key = estimate_key_chroma(y, sr)
    camelot_key = key_to_camelot(key)

    print("[analyze_track] Running allin1 ML model...")
    try:
        # Simplified call - uses the model to find BPM, beats, and structural labels
        ml_result = allin1.analyze(str(path.resolve()))
    except Exception as e:
        print(f"[analyze_track] CRITICAL ML Error: {e}")
        return None
    
    bpm = float(ml_result.bpm)
    beat_times = [float(b) for b in ml_result.beats]
    bar_start_times = estimate_bars_from_beats(beat_times, beats_per_bar=4)

    segments = []
    for seg in ml_result.segments:
        start_beat_idx, aligned_start_time = get_closest_beat(seg.start, beat_times)
        end_beat_idx, aligned_end_time = get_closest_beat(seg.end, beat_times)
        
        segments.append({
            "label": seg.label,
            "start_beat_index": start_beat_idx,
            "end_beat_index": end_beat_idx,
            "aligned_start_time": aligned_start_time,
            "aligned_end_time": aligned_end_time
        })

    print("[analyze_track] Done.")
    return {
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
        "segments": segments,
        "beat_times": beat_times,
        "bar_start_times": bar_start_times,
    }


def get_track_id_for_path(path: Path) -> str:
    """Resolve the deterministic track_id without running full analysis."""
    artist_tag, title_tag = read_tags(path)
    artist_fn, title_fn = parse_title_artist_from_filename(path)
    artist = artist_tag or artist_fn or "Unknown Artist"
    title = title_tag or title_fn or path.stem
    return slugify(f"{artist}_{title}")


def metadata_output_path(track_id: str, metadata_dir: Path = METADATA_DIR) -> Path:
    """Return the on-disk metadata path for a track ID."""
    return metadata_dir / f"{track_id}.json"


def load_metadata_file(metadata_path: Path) -> dict:
    """Load one metadata JSON file from disk."""
    with metadata_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_track_metadata(audio_path: Path, metadata_dir: Path = METADATA_DIR) -> dict | None:
    """Load cached metadata for a track or analyze and persist it if missing."""
    track_id = get_track_id_for_path(audio_path)
    output_path = metadata_output_path(track_id, metadata_dir)

    if output_path.is_file():
        print(f"[Metadata] Skipping {audio_path.name}: using cached {output_path.name}")
        return load_metadata_file(output_path)

    metadata = analyze_track(str(audio_path))
    if metadata is None:
        return None

    metadata_dir.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")

    print(f"[Metadata] Saved {output_path}")
    return metadata


def analyze_songs_directory(
    songs_dir: Path = SONGS_DIR,
    metadata_dir: Path = METADATA_DIR,
) -> list[dict]:
    """Analyze all supported audio files in a directory, reusing cached metadata."""
    if not songs_dir.exists():
        raise FileNotFoundError(f"songs/ folder not found: {songs_dir}")

    metadata_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for audio_path in sorted(songs_dir.iterdir()):
        if audio_path.suffix.lower() not in AUDIO_EXTS:
            continue
        metadata = ensure_track_metadata(audio_path, metadata_dir)
        if metadata is not None:
            results.append(metadata)
    return results

if __name__ == "__main__":
    try:
        analyzed_tracks = analyze_songs_directory()
    except FileNotFoundError as exc:
        print(f"[main] {exc}")
        raise SystemExit(1) from exc

    print(f"\n[main] Done. Processed {len(analyzed_tracks)} audio file(s).")
