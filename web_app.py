#!/usr/bin/env python3
"""Local web app for uploading tracks and rendering DJ transitions."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from get_song_metadata import AUDIO_EXTS, SONGS_DIR, analyze_songs_directory, ensure_track_metadata
from main import order_setlist_by_bpm
from render_transition import OUTPUTS_DIR, render_all_styles
from separate_stems import process_track
from transitions.core.audio_analysis import calculate_compatibility


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
METADATA_DIR = PROJECT_ROOT / "metadata"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")


def choose_pair_for_track(setlist: list[dict], track_id: str) -> tuple[str, str]:
    """Choose one adjacent pair involving the uploaded track."""
    for index, track in enumerate(setlist):
        if track["track_id"] != track_id:
            continue

        if index < len(setlist) - 1:
            return track_id, setlist[index + 1]["track_id"]
        if index > 0:
            return setlist[index - 1]["track_id"], track_id
        break

    raise ValueError("Need at least one neighboring track to build a transition.")


def build_style_payload(output_paths: list[Path]) -> list[dict]:
    """Convert output paths into frontend-friendly payloads."""
    styles = []
    for output_path in output_paths:
        relative_output = output_path.relative_to(OUTPUTS_DIR)
        styles.append(
            {
                "name": output_path.stem,
                "label": output_path.stem.replace("_", " "),
                "url": f"/outputs/{relative_output.as_posix()}",
                "saved_path": str(output_path.relative_to(PROJECT_ROOT)),
            }
        )
    return styles


def build_pair_payload(song_a_id: str, song_b_id: str, output_paths: list[Path]) -> dict:
    """Convert one rendered pair into frontend payload format."""
    return {
        "song_a_id": song_a_id,
        "song_b_id": song_b_id,
        "label": f"{song_a_id} -> {song_b_id}",
        "styles": build_style_payload(output_paths),
    }


@app.get("/")
def serve_index():
    """Serve the frontend entrypoint."""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/favicon.ico")
def favicon():
    """Avoid noisy 404s for favicon requests."""
    return ("", 204)


@app.get("/outputs/<path:filename>")
def serve_output(filename: str):
    """Serve rendered output audio files."""
    return send_from_directory(OUTPUTS_DIR, filename)


@app.get("/api/songs")
def list_songs():
    """Return locally analyzed songs for the Pitch Matcher UI."""
    if not METADATA_DIR.is_dir():
        return jsonify([])

    songs: list[dict] = []
    for metadata_path in sorted(METADATA_DIR.glob("*.json")):
        with metadata_path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        track_id = metadata.get("track_id")
        if not track_id:
            continue
        songs.append(
            {
                "track_id": str(track_id),
                "title": str(metadata.get("title") or track_id),
                "artist": str(metadata.get("artist") or "Unknown Artist"),
                "key": str(metadata.get("key") or "Unknown"),
                "camelot_key": str(metadata.get("camelot_key") or "Unknown"),
            }
        )

    songs.sort(key=lambda item: (item["title"].lower(), item["artist"].lower()))
    return jsonify(songs)


@app.post("/api/compare")
def compare_songs():
    """Run the advanced compatibility analysis for two selected songs."""
    payload = request.get_json(silent=True) or {}
    song_a_id = str(payload.get("song_a_id") or "").strip()
    song_b_id = str(payload.get("song_b_id") or "").strip()
    if not song_a_id or not song_b_id:
        return jsonify({"error": "song_a_id and song_b_id are required."}), 400

    try:
        result = calculate_compatibility(song_a_id, song_b_id)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"Comparison failed: {exc}"}), 500

    return jsonify(result)


@app.post("/process")
def process_upload():
    """Accept an uploaded song, run the local pipeline, and return playable output URLs."""
    uploaded_files = [file for file in request.files.getlist("files") if file and file.filename]
    if not uploaded_files:
        single_file = request.files.get("file")
        if single_file is not None and single_file.filename:
            uploaded_files = [single_file]
    if not uploaded_files:
        return jsonify({"error": "No file uploaded."}), 400

    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    uploaded_track_ids: list[str] = []
    for uploaded_file in uploaded_files:
        filename = Path(uploaded_file.filename).name
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_EXTS:
            return jsonify({"error": f"Unsupported file type: {filename}"}), 400

        saved_audio_path = SONGS_DIR / filename
        print(f"[Upload] Saving uploaded file to {saved_audio_path}")
        uploaded_file.save(saved_audio_path)

        print(f"[Upload] Ensuring metadata for {filename}...")
        uploaded_metadata = ensure_track_metadata(saved_audio_path)
        if uploaded_metadata is None:
            return jsonify({"error": f"Track analysis failed for {filename}."}), 500
        uploaded_track_ids.append(uploaded_metadata["track_id"])

    print("[Pipeline] Refreshing ordered metadata set...")
    analyzed_tracks = analyze_songs_directory(SONGS_DIR)
    setlist = order_setlist_by_bpm(analyzed_tracks)
    if len(setlist) < 2:
        return (
            jsonify(
                {
                    "error": "At least two songs are required in songs/ before a transition can be rendered."
                }
            ),
            400,
        )

    pairs_to_render: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for uploaded_track_id in uploaded_track_ids:
        try:
            pair = choose_pair_for_track(setlist, uploaded_track_id)
        except ValueError:
            continue
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            pairs_to_render.append(pair)

    if not pairs_to_render:
        return jsonify({"error": "Could not build any adjacent pairs from the uploaded songs."}), 400

    payload_pairs = []
    for song_a_id, song_b_id in pairs_to_render:
        print(f"[Render] Selected pair {song_a_id} -> {song_b_id}")

        print(f"[Stems] Ensuring stems for {song_a_id}")
        process_track(song_a_id)
        print(f"[Stems] Ensuring stems for {song_b_id}")
        process_track(song_b_id)

        pair_output_dir = OUTPUTS_DIR / f"{song_a_id}_to_{song_b_id}"
        print(f"[Render] Rendering styles into {pair_output_dir}")
        rendered_paths = render_all_styles(song_a_id, song_b_id, pair_output_dir)
        payload_pairs.append(build_pair_payload(song_a_id, song_b_id, rendered_paths))

    first_pair = payload_pairs[0]
    first_style = first_pair["styles"][0]
    payload = {
        "pairs": payload_pairs,
        "url": first_style["url"],
        "saved_path": first_style["saved_path"],
        "pair_label": first_pair["label"],
    }
    return jsonify(payload)


if __name__ == "__main__":
    print(f"[Server] Project root: {PROJECT_ROOT}")
    print("[Server] Starting local web app on http://localhost:8080")
    # Changed port from 5000 to 8080
    app.run(host="127.0.0.1", port=8080, debug=True)
