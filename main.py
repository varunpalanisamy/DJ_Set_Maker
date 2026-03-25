#!/usr/bin/env python3
"""End-to-end DJ pipeline orchestrator."""

from __future__ import annotations

from pathlib import Path

from get_song_metadata import AUDIO_EXTS, SONGS_DIR, analyze_songs_directory
from render_transition import OUTPUTS_DIR, render_all_styles
from separate_stems import STEMS_DIR, process_track


PROJECT_ROOT = Path(__file__).resolve().parent


def discover_audio_files(songs_dir: Path) -> list[Path]:
    """Return supported audio files from the songs directory."""
    if not songs_dir.exists():
        raise FileNotFoundError(f"songs/ folder not found: {songs_dir}")
    return sorted(
        path for path in songs_dir.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTS
    )


def order_setlist_by_bpm(tracks: list[dict]) -> list[dict]:
    """Order tracks from slowest to fastest BPM."""
    return sorted(tracks, key=lambda track: (float(track["bpm"]), track["track_id"]))


def ensure_stems_for_tracks(tracks: list[dict]) -> None:
    """Generate Demucs stems for each track if they do not already exist."""
    STEMS_DIR.mkdir(parents=True, exist_ok=True)
    for index, track in enumerate(tracks, start=1):
        track_id = track["track_id"]
        print(f"[Stems] ({index}/{len(tracks)}) Ensuring stems for {track_id}...")
        process_track(track_id)


def render_adjacent_pairs(setlist: list[dict]) -> None:
    """Render all transition styles for each adjacent pair in the ordered setlist."""
    if len(setlist) < 2:
        print("[Render] Need at least two tracks to render transitions. Skipping.")
        return

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    for first, second in zip(setlist, setlist[1:]):
        song_a_id = first["track_id"]
        song_b_id = second["track_id"]
        pair_output_dir = OUTPUTS_DIR / f"{song_a_id}_to_{song_b_id}"
        print(f"[Render] Processing transition: {song_a_id} -> {song_b_id}...")
        pair_output_dir.mkdir(parents=True, exist_ok=True)
        render_all_styles(song_a_id, song_b_id, pair_output_dir)


def main() -> None:
    """Run the full analyze -> stems -> order -> render pipeline."""
    print("[Pipeline] Scanning songs directory...")
    audio_files = discover_audio_files(SONGS_DIR)
    print(f"[Pipeline] Found {len(audio_files)} audio file(s) in {SONGS_DIR}.")
    if not audio_files:
        print("[Pipeline] No supported audio files found. Nothing to do.")
        return

    print("[Pipeline] Starting metadata analysis and cache reuse...")
    analyzed_tracks = analyze_songs_directory(SONGS_DIR)
    if not analyzed_tracks:
        print("[Pipeline] No metadata could be generated. Aborting.")
        return
    print(f"[Pipeline] Metadata ready for {len(analyzed_tracks)} track(s).")

    print("[Pipeline] Ensuring stems exist for every analyzed track...")
    ensure_stems_for_tracks(analyzed_tracks)
    print("[Pipeline] Stem generation phase complete.")

    print("[Setlist] Ordering tracks by ascending BPM...")
    setlist = order_setlist_by_bpm(analyzed_tracks)
    ordered_ids = [track["track_id"] for track in setlist]
    print(f"[Setlist] Ordered {len(setlist)} tracks by BPM.")
    print(f"[Setlist] {ordered_ids}")

    print("[Pipeline] Rendering transition styles for adjacent pairs...")
    render_adjacent_pairs(setlist)
    print("[Pipeline] All done.")


if __name__ == "__main__":
    main()
