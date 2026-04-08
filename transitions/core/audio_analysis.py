"""Advanced harmonic and textural compatibility analysis for song pairs."""

from __future__ import annotations

import math
from pathlib import Path

import librosa
import numpy as np

from transitions.core.structural_logic import load_metadata


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STEMS_DIR = PROJECT_ROOT / "stems"
PITCH_CLASS_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
PITCH_CLASS_MAP = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "F": 5,
    "E#": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}
SEMITONE_TO_MAJOR_KEY = {
    0: "C",
    1: "C#",
    2: "D",
    3: "D#",
    4: "E",
    5: "F",
    6: "F#",
    7: "G",
    8: "G#",
    9: "A",
    10: "A#",
    11: "B",
}
SEMITONE_TO_CAM_MAJOR = {
    0: "8B",
    1: "3B",
    2: "10B",
    3: "5B",
    4: "12B",
    5: "7B",
    6: "2B",
    7: "9B",
    8: "4B",
    9: "11B",
    10: "6B",
    11: "1B",
}
SEMITONE_TO_CAM_MINOR = {
    0: "5A",
    1: "12A",
    2: "7A",
    3: "2A",
    4: "9A",
    5: "4A",
    6: "11A",
    7: "6A",
    8: "1A",
    9: "8A",
    10: "3A",
    11: "10A",
}


def cosine_similarity(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    """Return cosine similarity between two vectors."""
    denom = float(np.linalg.norm(vector_a) * np.linalg.norm(vector_b))
    if denom <= 0:
        return 0.0
    return float(np.dot(vector_a, vector_b) / denom)


def clamp_score(value: float) -> float:
    """Clamp a score into the 0-100 range."""
    return max(0.0, min(100.0, value))


def parse_key_signature(key: str) -> tuple[int, str] | None:
    """Convert a key label like Dm or G# into (pitch class, mode)."""
    if not key:
        return None
    cleaned = str(key).strip()
    mode = "minor" if cleaned.endswith("m") else "major"
    tonic = cleaned[:-1] if cleaned.endswith("m") else cleaned
    tonic = tonic.upper().replace("♯", "#").replace("♭", "B")
    semitone = PITCH_CLASS_MAP.get(tonic)
    if semitone is None:
        return None
    return semitone, mode


def camelot_neighbor_match(camelot_a: str, camelot_b: str) -> bool:
    """Return True if two Camelot keys are adjacent on the same ring."""
    if not camelot_a or not camelot_b:
        return False
    try:
        num_a = int(camelot_a[:-1])
        num_b = int(camelot_b[:-1])
    except ValueError:
        return False
    mode_a = camelot_a[-1].upper()
    mode_b = camelot_b[-1].upper()
    if mode_a != mode_b:
        return False
    clockwise = 1 if num_a == 12 else num_a + 1
    counterclockwise = 12 if num_a == 1 else num_a - 1
    return num_b in {clockwise, counterclockwise}


def semitone_to_key_name(semitone: int, mode: str) -> str:
    """Convert a semitone + mode pair back into a simple key label."""
    tonic = SEMITONE_TO_MAJOR_KEY[int(semitone) % 12]
    return f"{tonic}m" if mode == "minor" else tonic


def semitone_mode_to_camelot(semitone: int, mode: str) -> str:
    """Convert semitone + mode into Camelot notation."""
    semitone = int(semitone) % 12
    if mode == "minor":
        return SEMITONE_TO_CAM_MINOR[semitone]
    return SEMITONE_TO_CAM_MAJOR[semitone]


def bpm_match_details(bpm_a: float, bpm_b: float) -> dict:
    """Score tempo compatibility using standard, double-time, and half-time interpretations."""
    candidates = (
        ("standard", bpm_a, False),
        ("double_time", bpm_a * 2.0, True),
        ("half_time", bpm_a / 2.0 if bpm_a > 0 else 0.0, False),
    )
    best_mode, best_bpm, is_double_time = min(candidates, key=lambda item: abs(item[1] - bpm_b))
    gap_ratio = abs(best_bpm - bpm_b) / max(best_bpm, bpm_b, 1e-9)
    if gap_ratio < 0.03:
        score = 100.0
    elif gap_ratio <= 0.08:
        score = 80.0
    else:
        score = clamp_score(80.0 - ((gap_ratio - 0.08) * 600.0))
    return {
        "score": score,
        "effective_gap_ratio": gap_ratio,
        "effective_bpm_a": best_bpm,
        "mode": best_mode,
        "is_double_time": is_double_time,
    }


def harmonic_match_details(
    metadata_a: dict,
    metadata_b: dict,
    semitone_b_override: int | None = None,
) -> dict:
    """Score harmonic compatibility from metadata before DSP fallback."""
    key_a = parse_key_signature(str(metadata_a.get("key") or ""))
    key_b = parse_key_signature(str(metadata_b.get("key") or ""))
    if not key_a or not key_b:
        return {
            "score": 0.0,
            "label": "Unknown key",
            "is_dominant_tonic": False,
            "metadata_matched": False,
            "category_rank": -1,
        }

    semitone_a, mode_a = key_a
    original_semitone_b, mode_b = key_b
    semitone_b = original_semitone_b if semitone_b_override is None else int(semitone_b_override) % 12
    camelot_a = semitone_mode_to_camelot(semitone_a, mode_a)
    camelot_b = semitone_mode_to_camelot(semitone_b, mode_b)
    interval = (semitone_b - semitone_a) % 12

    if semitone_a == semitone_b and mode_a == mode_b:
        return {
            "score": 100.0,
            "label": "Direct key match",
            "is_dominant_tonic": False,
            "metadata_matched": True,
            "category_rank": 4,
        }

    if interval in {5, 7}:
        return {
            "score": 95.0,
            "label": "Functional harmony match",
            "is_dominant_tonic": True,
            "metadata_matched": True,
            "category_rank": 3,
        }

    if mode_a != mode_b and interval in {3, 9}:
        return {
            "score": 88.0,
            "label": "Relative major/minor match",
            "is_dominant_tonic": False,
            "metadata_matched": True,
            "category_rank": 2,
        }

    if camelot_neighbor_match(camelot_a, camelot_b):
        return {
            "score": 82.0,
            "label": "Camelot neighbor match",
            "is_dominant_tonic": False,
            "metadata_matched": True,
            "category_rank": 1,
        }

    return {
        "score": 30.0,
        "label": "Metadata key clash",
        "is_dominant_tonic": False,
        "metadata_matched": False,
        "category_rank": 0,
    }


def format_shift_label(shift: int, new_target_key: str, harmonic_label: str) -> str:
    """Build a user-facing pitch-shift instruction."""
    if shift == 0:
        return "No semitone shift needed."
    direction = "up" if shift > 0 else "down"
    semitone_word = "semitone" if abs(shift) == 1 else "semitones"
    return (
        f"Shift Song B {direction} {abs(shift)} {semitone_word} "
        f"to reach {new_target_key} for a {harmonic_label.lower()}."
    )


def find_best_semitone_shift(metadata_a: dict, metadata_b: dict) -> dict:
    """Search a small semitone window for the strongest harmonic alignment."""
    key_b = parse_key_signature(str(metadata_b.get("key") or ""))
    if not key_b:
        return {
            "suggested_shift": 0,
            "new_target_key": str(metadata_b.get("key") or "Unknown"),
            "shift_label": "No semitone shift available.",
            "harmonic": harmonic_match_details(metadata_a, metadata_b),
        }

    original_harmonic = harmonic_match_details(metadata_a, metadata_b)
    if original_harmonic["label"] in {"Functional harmony match", "Camelot neighbor match"}:
        return {
            "suggested_shift": 0,
            "new_target_key": str(metadata_b.get("key") or "Unknown"),
            "shift_label": "No semitone shift needed.",
            "harmonic": original_harmonic,
        }

    original_semitone_b, mode_b = key_b
    best_shift = 0
    best_harmonic = original_harmonic

    for shift in (-2, -1, 0, 1, 2):
        shifted_semitone_b = (original_semitone_b + shift) % 12
        shifted_harmonic = harmonic_match_details(
            metadata_a,
            metadata_b,
            semitone_b_override=shifted_semitone_b,
        )
        if (
            shifted_harmonic["category_rank"] > best_harmonic["category_rank"]
            or (
                shifted_harmonic["category_rank"] == best_harmonic["category_rank"]
                and shifted_harmonic["score"] > best_harmonic["score"]
            )
            or (
                shifted_harmonic["category_rank"] == best_harmonic["category_rank"]
                and shifted_harmonic["score"] == best_harmonic["score"]
                and abs(shift) < abs(best_shift)
            )
        ):
            best_shift = shift
            best_harmonic = shifted_harmonic

    new_target_key = semitone_to_key_name((original_semitone_b + best_shift) % 12, mode_b)
    return {
        "suggested_shift": best_shift,
        "new_target_key": new_target_key,
        "shift_label": format_shift_label(best_shift, new_target_key, best_harmonic["label"]),
        "harmonic": best_harmonic,
    }


def resolve_audio_path(metadata: dict) -> Path:
    """Return a usable source path for DSP analysis."""
    file_path = metadata.get("file_path")
    if file_path:
        candidate = Path(str(file_path))
        if candidate.is_file():
            return candidate

    track_id = str(metadata.get("track_id") or metadata.get("_resolved_track_id") or "")
    stem_dir = STEMS_DIR / track_id
    for stem_name in ("other.mp3", "other.wav", "drums.mp3", "drums.wav", "vocals.mp3", "vocals.wav"):
        candidate = stem_dir / stem_name
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(f"Could not resolve audio for track '{track_id}'.")


def load_analysis_audio(metadata: dict, duration_sec: float = 30.0) -> tuple[np.ndarray, int]:
    """Load the first analysis window for one track."""
    audio_path = resolve_audio_path(metadata)
    return librosa.load(audio_path, sr=None, mono=True, duration=duration_sec)


def chroma_similarity_score(chroma_similarity: float) -> float:
    """Map average chroma cosine similarity into a harmonic score."""
    if chroma_similarity >= 0.95:
        return 100.0
    if chroma_similarity >= 0.88:
        return 92.0
    if chroma_similarity >= 0.8:
        return 82.0
    if chroma_similarity >= 0.7:
        return 68.0
    return clamp_score(chroma_similarity * 70.0)


def inverse_ratio_similarity(value_a: float, value_b: float) -> float:
    """Return a 0-1 similarity score from two positive values."""
    if value_a <= 0 and value_b <= 0:
        return 1.0
    if value_a <= 0 or value_b <= 0:
        return 0.0
    return min(value_a, value_b) / max(value_a, value_b)


def dsp_texture_details(metadata_a: dict, metadata_b: dict) -> dict:
    """Run the librosa-based audio texture analysis."""
    y_a, sr_a = load_analysis_audio(metadata_a)
    y_b, sr_b = load_analysis_audio(metadata_b)

    chroma_a = librosa.feature.chroma_stft(y=y_a, sr=sr_a)
    chroma_b = librosa.feature.chroma_stft(y=y_b, sr=sr_b)
    avg_chroma_a = np.mean(chroma_a, axis=1)
    avg_chroma_b = np.mean(chroma_b, axis=1)
    chroma_similarity = cosine_similarity(avg_chroma_a, avg_chroma_b)

    contrast_a = librosa.feature.spectral_contrast(y=y_a, sr=sr_a)
    contrast_b = librosa.feature.spectral_contrast(y=y_b, sr=sr_b)
    avg_contrast_a = np.mean(contrast_a, axis=1)
    avg_contrast_b = np.mean(contrast_b, axis=1)
    contrast_similarity = cosine_similarity(avg_contrast_a, avg_contrast_b)

    onset_a = librosa.onset.onset_strength(y=y_a, sr=sr_a)
    onset_b = librosa.onset.onset_strength(y=y_b, sr=sr_b)
    onset_var_a = float(np.var(onset_a))
    onset_var_b = float(np.var(onset_b))
    onset_similarity = inverse_ratio_similarity(onset_var_a, onset_var_b)

    energy_a = float(metadata_a.get("energy_score") or 0.0)
    energy_b = float(metadata_b.get("energy_score") or 0.0)
    loudness_a = abs(float(metadata_a.get("loudness_db") or 0.0))
    loudness_b = abs(float(metadata_b.get("loudness_db") or 0.0))
    energy_similarity = inverse_ratio_similarity(energy_a, energy_b)
    loudness_similarity = inverse_ratio_similarity(loudness_a, loudness_b)

    texture_score = (
        (contrast_similarity * 45.0)
        + (onset_similarity * 35.0)
        + (energy_similarity * 10.0)
        + (loudness_similarity * 10.0)
    )
    if energy_similarity >= 0.85 and loudness_similarity >= 0.85:
        texture_score = clamp_score(texture_score + 8.0)

    return {
        "texture_score": clamp_score(texture_score),
        "chroma_similarity": chroma_similarity,
        "chroma_score": chroma_similarity_score(chroma_similarity),
        "contrast_similarity": contrast_similarity,
        "onset_similarity": onset_similarity,
        "energy_similarity": energy_similarity,
        "loudness_similarity": loudness_similarity,
    }


def build_explanation(tempo: dict, harmonic: dict, dsp: dict) -> str:
    """Create a concise human-readable compatibility explanation."""
    parts: list[str] = []

    if harmonic["is_dominant_tonic"]:
        parts.append("Matches via Dominant-Tonic relationship")
    else:
        parts.append(harmonic["label"])

    if tempo["mode"] == "double_time":
        parts.append("with a strong double-time tempo fit")
    elif tempo["mode"] == "half_time":
        parts.append("with a usable half-time tempo fit")
    else:
        parts.append("with a close tempo match")

    if dsp["texture_score"] >= 80:
        parts.append("and similar transients / texture")
    elif dsp["chroma_score"] >= harmonic["score"]:
        parts.append("supported by the chroma similarity in the audio")

    return " ".join(parts) + "."


def calculate_compatibility(song_a_id: str, song_b_id: str) -> dict:
    """Run the full metadata + DSP compatibility pass for two tracks."""
    metadata_a = load_metadata(song_a_id)
    metadata_b = load_metadata(song_b_id)

    tempo = bpm_match_details(float(metadata_a["bpm"]), float(metadata_b["bpm"]))
    shift_recommendation = find_best_semitone_shift(metadata_a, metadata_b)
    harmonic = shift_recommendation["harmonic"]
    dsp = dsp_texture_details(metadata_a, metadata_b)

    harmonic_score = max(harmonic["score"], dsp["chroma_score"])
    if dsp["chroma_score"] > harmonic["score"]:
        harmonic_label = f"{harmonic['label']} overridden by strong chroma similarity"
    else:
        harmonic_label = harmonic["label"]

    total_score = (
        (tempo["score"] * 0.35)
        + (harmonic_score * 0.4)
        + (dsp["texture_score"] * 0.25)
    )
    total_score = round(clamp_score(total_score), 1)

    return {
        "song_a_id": song_a_id,
        "song_b_id": song_b_id,
        "total_score": total_score,
        "is_dominant_tonic": harmonic["is_dominant_tonic"],
        "is_double_time": tempo["is_double_time"],
        "suggested_shift": int(shift_recommendation["suggested_shift"]),
        "new_target_key": shift_recommendation["new_target_key"],
        "shift_label": shift_recommendation["shift_label"],
        "explanation": build_explanation(tempo, harmonic, dsp),
        "breakdown": {
            "tempo": {
                "score": round(tempo["score"], 1),
                "mode": tempo["mode"],
                "effective_gap_percent": round(tempo["effective_gap_ratio"] * 100.0, 2),
                "effective_bpm_a": round(float(tempo["effective_bpm_a"]), 2),
                "bpm_b": round(float(metadata_b["bpm"]), 2),
            },
            "harmonic": {
                "score": round(harmonic_score, 1),
                "label": harmonic_label,
                "metadata_score": round(harmonic["score"], 1),
                "chroma_score": round(dsp["chroma_score"], 1),
                "suggested_shift": int(shift_recommendation["suggested_shift"]),
                "new_target_key": shift_recommendation["new_target_key"],
                "shift_label": shift_recommendation["shift_label"],
            },
            "texture": {
                "score": round(dsp["texture_score"], 1),
                "contrast_similarity": round(dsp["contrast_similarity"], 3),
                "onset_similarity": round(dsp["onset_similarity"], 3),
                "energy_similarity": round(dsp["energy_similarity"], 3),
                "loudness_similarity": round(dsp["loudness_similarity"], 3),
            },
        },
    }
