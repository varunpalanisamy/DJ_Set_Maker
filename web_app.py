#!/usr/bin/env python3
"""Local web app for uploading tracks and rendering DJ transitions."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from pydub import AudioSegment

from get_song_metadata import AUDIO_EXTS, SONGS_DIR, analyze_songs_directory, ensure_track_metadata
from main import order_setlist_by_bpm
from render_transition import OUTPUTS_DIR, render_all_styles
from separate_stems import STEMS_DIR, process_track
from transitions.core.audio_analysis import calculate_compatibility
from transitions.core.structural_logic import (
    get_optimal_exit_time,
    get_song_entry_time,
    load_metadata as load_track_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
METADATA_DIR = PROJECT_ROOT / "metadata"
TEMP_VIZ_DIR = PROJECT_ROOT / "temp_viz"
STYLE_NAMES = ["Style_A", "Style_B", "Style_C"]

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


def all_transitions_rendered(pair_output_dir: Path) -> bool:
    """Return True when all 6 output files (3 styles × constant + gradual) already exist."""
    for name in STYLE_NAMES:
        if not (pair_output_dir / f"{name}.mp3").is_file():
            return False
        if not (pair_output_dir / "gradual_bpm" / f"{name}.mp3").is_file():
            return False
    return True


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


@app.get("/stems/<song_id>/<filename>")
def serve_stem(song_id: str, filename: str):
    """Serve individual stem files for the visualizer."""
    return send_from_directory(STEMS_DIR / song_id, filename)


@app.get("/temp_viz/<path:filename>")
def serve_temp_viz(filename: str):
    """Serve concatenated visualization audio files."""
    return send_from_directory(TEMP_VIZ_DIR, filename)


@app.post("/api/stem_visualizer/prepare")
def prepare_stem_visualizer():
    """Ensure stems exist, concatenate them for visualization, and return timing info."""
    payload = request.get_json(silent=True) or {}
    song_a_id = str(payload.get("song_a_id") or "").strip()
    song_b_id = str(payload.get("song_b_id") or "").strip()

    if not song_a_id or not song_b_id:
        return jsonify({"error": "song_a_id and song_b_id are required."}), 400

    try:
        print(f"[StemViz] Ensuring stems for {song_a_id}")
        process_track(song_a_id)
        print(f"[StemViz] Ensuring stems for {song_b_id}")
        process_track(song_b_id)

        meta_a = load_track_metadata(song_a_id)
        meta_b = load_track_metadata(song_b_id)
        song_a_exit_time = get_optimal_exit_time(meta_a)
        song_b_entry_time = get_song_entry_time(meta_b)

        TEMP_VIZ_DIR.mkdir(parents=True, exist_ok=True)
        concat_dir = TEMP_VIZ_DIR / f"{song_a_id}_to_{song_b_id}"
        concat_dir.mkdir(parents=True, exist_ok=True)

        stem_names = ["vocals", "drums", "bass", "other"]

        # Skip concatenation if all output files are already current
        concat_exists = all((concat_dir / f"{s}.mp3").is_file() for s in stem_names)

        stem_urls: dict[str, str] = {}
        song_a_duration_sec: float | None = None

        if not concat_exists:
            print(f"[StemViz] Concatenating stems for visualization...")
            for stem in stem_names:
                path_a = STEMS_DIR / song_a_id / f"{stem}.mp3"
                path_b = STEMS_DIR / song_b_id / f"{stem}.mp3"

                if not path_a.is_file() or not path_b.is_file():
                    return jsonify({"error": f"Stem file missing: {stem}"}), 500

                seg_a = AudioSegment.from_mp3(str(path_a))
                seg_b = AudioSegment.from_mp3(str(path_b))

                if song_a_duration_sec is None:
                    song_a_duration_sec = len(seg_a) / 1000.0

                combined = seg_a + seg_b
                out_path = concat_dir / f"{stem}.mp3"
                combined.export(str(out_path), format="mp3", bitrate="128k")
        else:
            print(f"[StemViz] Reusing cached concatenated stems.")

        if song_a_duration_sec is None:
            # Read duration from cached file
            seg_a = AudioSegment.from_mp3(str(STEMS_DIR / song_a_id / "vocals.mp3"))
            song_a_duration_sec = len(seg_a) / 1000.0

        for stem in stem_names:
            stem_urls[stem] = f"/temp_viz/{song_a_id}_to_{song_b_id}/{stem}.mp3"

        song_a_dur = song_a_duration_sec or 0.0
        return jsonify({
            "stems": stem_urls,
            "song_a_exit_time": song_a_exit_time,
            "song_a_duration": song_a_dur,
            "song_b_entry_time": song_b_entry_time,
            "song_b_entry_in_combined": song_a_dur + song_b_entry_time,
        })

    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"Preparation failed: {exc}"}), 500


@app.post("/api/stem_visualizer/render")
def render_stem_transition():
    """Render a specific transition style and return its URL."""
    payload = request.get_json(silent=True) or {}
    song_a_id = str(payload.get("song_a_id") or "").strip()
    song_b_id = str(payload.get("song_b_id") or "").strip()
    style_name = str(payload.get("style") or "Style_A").strip()
    gradual = bool(payload.get("gradual", False))

    if not song_a_id or not song_b_id:
        return jsonify({"error": "song_a_id and song_b_id are required."}), 400

    if style_name not in STYLE_NAMES:
        return jsonify({"error": f"style must be one of {STYLE_NAMES}."}), 400

    try:
        process_track(song_a_id)
        process_track(song_b_id)

        pair_output_dir = OUTPUTS_DIR / f"{song_a_id}_to_{song_b_id}"

        if not all_transitions_rendered(pair_output_dir):
            print(f"[StemViz] Rendering all styles for {song_a_id} -> {song_b_id}")
            render_all_styles(song_a_id, song_b_id, pair_output_dir)

        style_path = (
            pair_output_dir / "gradual_bpm" / f"{style_name}.mp3"
            if gradual
            else pair_output_dir / f"{style_name}.mp3"
        )

        if not style_path.is_file():
            return jsonify({"error": f"Output file not found after rendering: {style_path}"}), 404

        relative = style_path.relative_to(OUTPUTS_DIR)
        label = style_name.replace("_", " ") + (" · Gradual" if gradual else " · Constant")
        return jsonify({
            "url": f"/outputs/{relative.as_posix()}",
            "saved_path": str(style_path.relative_to(PROJECT_ROOT)),
            "label": label,
        })

    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"Render failed: {exc}"}), 500


if __name__ == "__main__":
    print(f"[Server] Project root: {PROJECT_ROOT}")
    print("[Server] Starting local web app on http://localhost:8080")
    # Changed port from 5000 to 8080
    app.run(host="127.0.0.1", port=8080, debug=True)
