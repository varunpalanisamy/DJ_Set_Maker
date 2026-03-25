#!/usr/bin/env python3
"""Separate setlist tracks into Demucs stems (MP3 bypass)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SETLIST_PATH = PROJECT_ROOT / "setlist.json"
METADATA_DIR = PROJECT_ROOT / "metadata"
STEMS_DIR = PROJECT_ROOT / "stems"
TEMP_DIR = PROJECT_ROOT / "stems_temp"

# CHANGED: We now expect MP3s instead of WAVs
EXPECTED_STEMS = ("vocals.mp3", "drums.mp3", "bass.mp3", "other.mp3")
DEMUCS_MODEL = "htdemucs"


def load_setlist(setlist_path: Path) -> list[str]:
    """Load the ordered setlist entries from disk."""
    if not setlist_path.exists():
        raise FileNotFoundError(f"Setlist file not found: {setlist_path}")

    with setlist_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError("setlist.json must contain a JSON array.")

    validated_entries: list[str] = []
    for index, item in enumerate(data):
        if not isinstance(item, str):
            raise ValueError(f"Setlist entry at index {index} is not a string: {item!r}")
        validated_entries.append(item)

    return validated_entries


def load_metadata(track_id: str) -> dict:
    """Load metadata JSON for a given track ID."""
    metadata_path = METADATA_DIR / f"{track_id}.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found for track '{track_id}': {metadata_path}")

    with metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)

    if not isinstance(metadata, dict):
        raise ValueError(f"Metadata for track '{track_id}' is not a JSON object.")

    return metadata


def stems_are_complete(track_id: str) -> bool:
    """Check whether all expected stem files already exist for a track."""
    track_stem_dir = STEMS_DIR / track_id
    if not track_stem_dir.is_dir():
        return False

    return all((track_stem_dir / stem_name).is_file() for stem_name in EXPECTED_STEMS)


def prepare_output_dir(track_id: str) -> Path:
    """Create or reset the final stem folder for a track."""
    track_stem_dir = STEMS_DIR / track_id
    if track_stem_dir.exists():
        shutil.rmtree(track_stem_dir)
    track_stem_dir.mkdir(parents=True, exist_ok=True)
    return track_stem_dir


def run_demucs(file_path: Path) -> None:
    """Invoke the Demucs CLI for one input file."""
    command = [
        "demucs",
        "-n",
        DEMUCS_MODEL,
        "--mp3",  # CHANGED: Force Demucs to bypass PyTorch saving and use lameenc
        "-o",
        str(TEMP_DIR),
        str(file_path),
    ]

    print(f"  Running Demucs on: {file_path}")
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Demucs CLI was not found. Install Demucs and ensure 'demucs' is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Demucs failed with exit code {exc.returncode}") from exc


def find_demucs_output_dir(file_path: Path) -> Path:
    """Locate the Demucs output folder for the processed file."""
    output_dir = TEMP_DIR / DEMUCS_MODEL / file_path.stem
    if not output_dir.is_dir():
        raise FileNotFoundError(
            f"Expected Demucs output directory was not created: {output_dir}"
        )
    return output_dir


def move_stems(track_id: str, demucs_output_dir: Path) -> None:
    """Move the normalized Demucs stems into stems/<track_id>/."""
    destination_dir = prepare_output_dir(track_id)

    for stem_name in EXPECTED_STEMS:
        source_path = demucs_output_dir / stem_name
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing expected stem file: {source_path}")

        destination_path = destination_dir / stem_name
        shutil.move(str(source_path), str(destination_path))


def cleanup_temp_dir() -> None:
    """Remove Demucs temporary output after each track."""
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)


def process_track(track_id: str) -> None:
    """Process one setlist track unless its stems already exist."""
    if stems_are_complete(track_id):
        print(f"Skipping '{track_id}': all 4 stems already exist.")
        return

    print(f"Processing track: {track_id}")

    metadata = load_metadata(track_id)
    file_path_value = metadata.get("file_path")
    if not file_path_value:
        raise ValueError(f"Metadata for track '{track_id}' does not contain 'file_path'.")

    file_path = Path(file_path_value)
    if not file_path.is_file():
        raise FileNotFoundError(f"Audio file for track '{track_id}' was not found: {file_path}")

    cleanup_temp_dir()
    run_demucs(file_path)
    demucs_output_dir = find_demucs_output_dir(file_path)
    move_stems(track_id, demucs_output_dir)
    cleanup_temp_dir()

    print(f"Finished track: {track_id}")


def main() -> None:
    """Run stem separation for the current setlist."""
    print("Loading setlist...")
    setlist_entries = load_setlist(SETLIST_PATH)

    STEMS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Stem output directory ready: {STEMS_DIR}")

    for index, entry in enumerate(setlist_entries, start=1):
        print(f"\n[{index}/{len(setlist_entries)}] Setlist item: {entry}")
        if entry == "BIG_JUMP":
            print("Skipping transition marker: BIG_JUMP")
            continue

        try:
            process_track(entry)
        except Exception as exc:
            cleanup_temp_dir()
            print(f"Failed to process '{entry}': {exc}")

    print("\nStem separation pipeline finished.")


if __name__ == "__main__":
    main()