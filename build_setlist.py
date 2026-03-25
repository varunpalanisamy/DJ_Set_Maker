#!/usr/bin/env python3
"""Build a DJ setlist from analyzed track metadata."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_METADATA_DIR = Path("metadata")
DEFAULT_OUTPUT_PATH = Path("setlist.json")

# Heuristic weights for ranking compatible transitions.
UPHILL_BPM_WEIGHT = 3.0
ENERGY_WEIGHT = 1.5
KEY_MATCH_WEIGHT = 4.0
MODE_CHANGE_WEIGHT = 2.0
NEIGHBOR_KEY_WEIGHT = 3.0
BPM_CLOSENESS_WEIGHT = 2.0


@dataclass(frozen=True)
class Track:
    """Normalized track metadata used by the set builder."""

    track_id: str
    title: str | None
    bpm: float
    camelot_key: str
    energy_score: float
    raw: dict


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Order analyzed songs into a musically coherent DJ setlist."
    )
    parser.add_argument(
        "--metadata-dir",
        type=Path,
        default=DEFAULT_METADATA_DIR,
        help="Directory containing song metadata JSON files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for the output JSON setlist.",
    )
    parser.add_argument(
        "--start-track-id",
        type=str,
        default=None,
        help="Optional track_id to force as the first song in the set.",
    )
    return parser.parse_args()


def load_tracks(metadata_dir: Path) -> list[Track]:
    """Load and normalize track JSON files from disk."""
    if not metadata_dir.exists():
        raise FileNotFoundError(f"Metadata directory not found: {metadata_dir}")
    if not metadata_dir.is_dir():
        raise NotADirectoryError(f"Metadata path is not a directory: {metadata_dir}")

    tracks: list[Track] = []
    for json_path in sorted(metadata_dir.glob("*.json")):
        with json_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        track_id = data.get("track_id")
        bpm = data.get("bpm")
        camelot_key = data.get("camelot_key")

        if not track_id or bpm is None or not camelot_key:
            print(f"Skipping {json_path}: missing track_id, bpm, or camelot_key.")
            continue

        tracks.append(
            Track(
                track_id=str(track_id),
                title=data.get("title"),
                bpm=float(bpm),
                camelot_key=str(camelot_key).strip().upper(),
                energy_score=float(data.get("energy_score") or 0.0),
                raw=data,
            )
        )

    if not tracks:
        raise ValueError(f"No valid track metadata found in {metadata_dir}")

    return tracks


def parse_camelot(camelot_key: str) -> tuple[int, str]:
    """Split Camelot notation like '3A' into numeric and mode components."""
    cleaned = camelot_key.strip().upper()
    if len(cleaned) < 2:
        raise ValueError(f"Invalid Camelot key: {camelot_key}")

    number_part = cleaned[:-1]
    mode_part = cleaned[-1]

    if mode_part not in {"A", "B"}:
        raise ValueError(f"Invalid Camelot mode: {camelot_key}")

    number = int(number_part)
    if not 1 <= number <= 12:
        raise ValueError(f"Camelot number must be 1-12: {camelot_key}")

    return number, mode_part


def camelot_relation(source: Track, candidate: Track) -> str | None:
    """Return the harmonic relationship label when two tracks are compatible."""
    source_num, source_mode = parse_camelot(source.camelot_key)
    candidate_num, candidate_mode = parse_camelot(candidate.camelot_key)

    if source_num == candidate_num and source_mode == candidate_mode:
        return "exact"

    clockwise = 1 if source_num == 12 else source_num + 1
    counterclockwise = 12 if source_num == 1 else source_num - 1
    if source_mode == candidate_mode and candidate_num in {clockwise, counterclockwise}:
        return "neighbor"

    if source_num == candidate_num and source_mode != candidate_mode:
        return "mode_change"

    return None


def bpm_is_compatible(source: Track, candidate: Track, tolerance: float = 0.05) -> bool:
    """Check whether a candidate BPM is within the allowed percentage window."""
    max_difference = source.bpm * tolerance
    return abs(candidate.bpm - source.bpm) <= max_difference


def transition_score(source: Track, candidate: Track) -> float:
    """Score a compatible transition, favoring gradual upward momentum."""
    relation = camelot_relation(source, candidate)
    if relation is None or not bpm_is_compatible(source, candidate):
        return float("-inf")

    bpm_delta = candidate.bpm - source.bpm
    energy_delta = candidate.energy_score - source.energy_score
    bpm_distance_ratio = abs(bpm_delta) / max(source.bpm, 1.0)

    score = 0.0

    if relation == "exact":
        score += KEY_MATCH_WEIGHT
    elif relation == "neighbor":
        score += NEIGHBOR_KEY_WEIGHT
    elif relation == "mode_change":
        score += MODE_CHANGE_WEIGHT

    if bpm_delta >= 0:
        score += UPHILL_BPM_WEIGHT * bpm_delta
    else:
        score += bpm_delta

    score += ENERGY_WEIGHT * energy_delta
    score += BPM_CLOSENESS_WEIGHT * (1.0 - bpm_distance_ratio)

    return score


def pick_start_track(tracks: Iterable[Track], start_track_id: str | None) -> Track:
    """Choose the explicit start track or fall back to the lowest-BPM song."""
    track_list = list(tracks)
    if start_track_id is not None:
        for track in track_list:
            if track.track_id == start_track_id:
                return track
        raise ValueError(f"Start track_id not found: {start_track_id}")

    return min(track_list, key=lambda track: (track.bpm, -track.energy_score, track.track_id))


def find_best_next_track(current: Track, remaining: Iterable[Track]) -> Track | None:
    """Pick the highest-scoring compatible next track from the remaining pool."""
    compatible_tracks = []
    for candidate in remaining:
        score = transition_score(current, candidate)
        if score == float("-inf"):
            continue
        compatible_tracks.append((score, candidate))

    if not compatible_tracks:
        return None

    compatible_tracks.sort(
        key=lambda item: (
            item[0],
            item[1].bpm - current.bpm >= 0,
            item[1].bpm,
            item[1].energy_score,
        ),
        reverse=True,
    )
    return compatible_tracks[0][1]


def build_setlist(tracks: list[Track], start_track_id: str | None = None) -> list[Track | str]:
    """Assemble the setlist, forcing 'BIG_JUMP' markers when rules are broken."""
    remaining = tracks.copy()
    setlist: list[Track | str] = []

    current = pick_start_track(remaining, start_track_id)
    setlist.append(current)
    remaining.remove(current)

    while remaining:
        next_track = find_best_next_track(current, remaining)
        
        if next_track is not None:
            # Good transition found!
            setlist.append(next_track)
        else:
            # No compatible track found. Force a jump.
            # Pick the track with the closest BPM from the remaining pile to minimize damage.
            next_track = min(remaining, key=lambda t: abs(t.bpm - current.bpm))
            setlist.append("BIG_JUMP")
            setlist.append(next_track)

        remaining.remove(next_track)
        current = next_track

    return setlist


def print_setlist(setlist: list[Track | str]) -> None:
    """Print the final sequence, highlighting the big jumps."""
    print("\n--- Final DJ Setlist ---")
    track_num = 1
    for item in setlist:
        if isinstance(item, str):
            print(f"      ---> [ {item}: Bridge/FX transition needed ] <---")
        else:
            print(f"{track_num:02d}. {item.track_id:20} | {item.bpm:6.2f} BPM | {item.camelot_key:>3}")
            track_num += 1
    print("------------------------\n")


def save_setlist(output_data: list[str], output_path: Path) -> None:
    """Write the ordered track IDs and jump markers to disk."""
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(output_data, handle, indent=2)
        handle.write("\n")


def main() -> None:
    """Entrypoint for CLI usage."""
    args = parse_args()
    tracks = load_tracks(args.metadata_dir)
    
    # Build the setlist with Track objects and "BIG_JUMP" strings
    setlist = build_setlist(tracks, start_track_id=args.start_track_id)

    # Print nicely to console
    print_setlist(setlist)

    # Convert the setlist to a simple array of strings for the JSON
    json_output_data = []
    for item in setlist:
        if isinstance(item, str):
            json_output_data.append(item)
        else:
            json_output_data.append(item.track_id)

    save_setlist(json_output_data, args.output)
    print(f"Saved {len(tracks)} tracks to {args.output}")


if __name__ == "__main__":
    main()