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
from transitions.core.audio_math import (
    calculate_local_bpm,
    calculate_preceding_local_bpm,
    count_beats_in_window,
    get_beat_index_for_time,
    get_beat_timestamp,
    get_duration_of_virtual_beats,
    get_effective_bpm_match,
    snap_to_nearest_beat,
)
from transitions.core.structural_logic import (
    calculate_pickup_ms,
    get_optimal_exit_time,
    get_song_entry_time,
    load_metadata as load_track_metadata,
    get_song_b_drop_time,
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


def build_existing_style_payloads(pair_output_dir: Path) -> list[dict]:
    """Return all existing rendered styles for one pair directory."""
    output_paths: list[Path] = []
    for style_name in STYLE_NAMES:
        constant_path = pair_output_dir / f"{style_name}.mp3"
        gradual_path = pair_output_dir / "gradual_bpm" / f"{style_name}.mp3"
        if constant_path.is_file():
            output_paths.append(constant_path)
        if gradual_path.is_file():
            output_paths.append(gradual_path)
    return build_style_payload(output_paths)


def compute_transition_visualization(song_a_id: str, song_b_id: str) -> dict:
    """Compute shared visualization timing for a transition pair."""
    metadata_a = load_track_metadata(song_a_id)
    metadata_b = load_track_metadata(song_b_id)

    entry_time_sec = get_song_entry_time(metadata_b)
    drop_time_sec = get_song_b_drop_time(metadata_b, entry_time=entry_time_sec)
    local_entry_bpm_b = calculate_local_bpm(metadata_b, entry_time_sec, drop_time_sec)
    song_b_pickup_ms = calculate_pickup_ms(metadata_b, entry_time_sec)

    raw_song_a_exit_ms = int(round(get_optimal_exit_time(metadata_a) * 1000.0))
    exit_beat_index = get_beat_index_for_time(metadata_a, raw_song_a_exit_ms / 1000.0)
    local_exit_bpm_a = calculate_preceding_local_bpm(metadata_a, raw_song_a_exit_ms)
    _, _, song_a_beat_factor = get_effective_bpm_match(local_exit_bpm_a, local_entry_bpm_b)
    transition_beats = count_beats_in_window(metadata_b, entry_time_sec, drop_time_sec)
    if transition_beats <= 0:
        raise ValueError("Could not determine transition beat count for the visualizer.")

    transition_duration_ms = int(
        round(
            get_duration_of_virtual_beats(
                metadata_a,
                exit_beat_index,
                transition_beats,
                song_a_beat_factor,
            )
            * 1000.0
        )
    )
    original_song_b_entry_ms = int(round(entry_time_sec * 1000.0))
    original_song_b_entry_ms = snap_to_nearest_beat(original_song_b_entry_ms, metadata_b)
    transition_start_ms = int(round(get_beat_timestamp(metadata_a, exit_beat_index) * 1000.0))
    overlay_start_ms = max(0, transition_start_ms - song_b_pickup_ms)

    return {
        "song_a_id": song_a_id,
        "song_b_id": song_b_id,
        "song_a_exit_ms": transition_start_ms,
        "song_a_exit_time": transition_start_ms / 1000.0,
        "song_b_entry_ms": original_song_b_entry_ms,
        "song_b_entry_time": original_song_b_entry_ms / 1000.0,
        "song_b_pickup_ms": song_b_pickup_ms,
        "song_b_pickup_time": song_b_pickup_ms / 1000.0,
        "song_b_drop_ms": int(round(drop_time_sec * 1000.0)),
        "song_b_drop_time": drop_time_sec,
        "song_b_source_transition_ms": song_b_pickup_ms + max(0, int(round((drop_time_sec - entry_time_sec) * 1000.0))),
        "song_b_source_transition_time": (song_b_pickup_ms / 1000.0) + max(0.0, drop_time_sec - entry_time_sec),
        "transition_duration_ms": transition_duration_ms,
        "transition_duration_time": transition_duration_ms / 1000.0,
        "transition_end_ms": transition_start_ms + transition_duration_ms,
        "transition_end_time": (transition_start_ms + transition_duration_ms) / 1000.0,
        "overlay_start_ms": overlay_start_ms,
        "overlay_start_time": overlay_start_ms / 1000.0,
        "song_b_entry_on_timeline_ms": overlay_start_ms + song_b_pickup_ms,
        "song_b_entry_on_timeline": (overlay_start_ms + song_b_pickup_ms) / 1000.0,
    }


def build_aligned_visualizer_stems(song_a_id: str, song_b_id: str, timing: dict) -> dict[str, dict[str, str]]:
    """Create aligned Song A / Song B stem files for the shared visualizer timeline."""
    pair_dir = TEMP_VIZ_DIR / "aligned" / f"{song_a_id}_to_{song_b_id}"
    pair_dir.mkdir(parents=True, exist_ok=True)

    overlay_start_ms = int(timing["overlay_start_ms"])
    song_b_entry_ms = int(timing["song_b_entry_ms"])
    song_b_pickup_ms = int(timing["song_b_pickup_ms"])

    stem_urls: dict[str, dict[str, str]] = {"song_a": {}, "song_b": {}}
    longest_duration_ms = 0

    source_segments_a: dict[str, AudioSegment] = {}
    source_segments_b: dict[str, AudioSegment] = {}
    for stem_name in ("vocals", "drums", "bass", "other"):
        path_a = next(
            (candidate for candidate in (STEMS_DIR / song_a_id / f"{stem_name}.mp3", STEMS_DIR / song_a_id / f"{stem_name}.wav") if candidate.is_file()),
            None,
        )
        path_b = next(
            (candidate for candidate in (STEMS_DIR / song_b_id / f"{stem_name}.mp3", STEMS_DIR / song_b_id / f"{stem_name}.wav") if candidate.is_file()),
            None,
        )
        if path_a is None or path_b is None:
            raise FileNotFoundError(f"Stem file missing for {stem_name}.")

        source_segments_a[stem_name] = AudioSegment.from_file(path_a)
        source_segments_b[stem_name] = AudioSegment.from_file(path_b)

    excerpt_start_ms = max(0, song_b_entry_ms - song_b_pickup_ms)
    for stem_name in ("vocals", "drums", "bass", "other"):
        longest_duration_ms = max(
            longest_duration_ms,
            len(source_segments_a[stem_name]),
            overlay_start_ms + max(0, len(source_segments_b[stem_name]) - excerpt_start_ms),
        )

    silent_template = AudioSegment.silent(duration=0)
    padded_song_a_segments: dict[str, AudioSegment] = {}
    padded_song_b_segments: dict[str, AudioSegment] = {}
    for stem_name in ("vocals", "drums", "bass", "other"):
        song_a_segment = source_segments_a[stem_name]
        song_b_excerpt = source_segments_b[stem_name][excerpt_start_ms:]
        padded_song_a = song_a_segment + AudioSegment.silent(duration=max(0, longest_duration_ms - len(song_a_segment)))
        padded_song_b = (
            AudioSegment.silent(duration=overlay_start_ms, frame_rate=song_b_excerpt.frame_rate)
            + song_b_excerpt
        )
        padded_song_b += AudioSegment.silent(duration=max(0, longest_duration_ms - len(padded_song_b)))

        output_a = pair_dir / f"song_a_{stem_name}.mp3"
        output_b = pair_dir / f"song_b_{stem_name}.mp3"
        if not output_a.is_file():
            padded_song_a.export(output_a, format="mp3", bitrate="128k")
        if not output_b.is_file():
            padded_song_b.export(output_b, format="mp3", bitrate="128k")

        stem_urls["song_a"][stem_name] = f"/temp_viz/aligned/{song_a_id}_to_{song_b_id}/song_a_{stem_name}.mp3"
        stem_urls["song_b"][stem_name] = f"/temp_viz/aligned/{song_a_id}_to_{song_b_id}/song_b_{stem_name}.mp3"
        padded_song_a_segments[stem_name] = padded_song_a
        padded_song_b_segments[stem_name] = padded_song_b

    song_a_mix = (
        padded_song_a_segments["vocals"]
        .overlay(padded_song_a_segments["drums"])
        .overlay(padded_song_a_segments["bass"])
        .overlay(padded_song_a_segments["other"])
    )
    song_b_mix = (
        padded_song_b_segments["vocals"]
        .overlay(padded_song_b_segments["drums"])
        .overlay(padded_song_b_segments["bass"])
        .overlay(padded_song_b_segments["other"])
    )
    output_a_mix = pair_dir / "song_a_mix.mp3"
    output_b_mix = pair_dir / "song_b_mix.mp3"
    if not output_a_mix.is_file():
        song_a_mix.export(output_a_mix, format="mp3", bitrate="128k")
    if not output_b_mix.is_file():
        song_b_mix.export(output_b_mix, format="mp3", bitrate="128k")
    stem_urls["song_a"]["mix"] = f"/temp_viz/aligned/{song_a_id}_to_{song_b_id}/song_a_mix.mp3"
    stem_urls["song_b"]["mix"] = f"/temp_viz/aligned/{song_a_id}_to_{song_b_id}/song_b_mix.mp3"

    timing["total_duration_ms"] = longest_duration_ms
    timing["total_duration"] = longest_duration_ms / 1000.0
    return stem_urls


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
    """Ensure stems exist, prepare aligned visualizer tracks, and report existing renders."""
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
        TEMP_VIZ_DIR.mkdir(parents=True, exist_ok=True)
        timing = compute_transition_visualization(song_a_id, song_b_id)
        stem_urls = build_aligned_visualizer_stems(song_a_id, song_b_id, timing)
        pair_output_dir = OUTPUTS_DIR / f"{song_a_id}_to_{song_b_id}"
        existing_styles = build_existing_style_payloads(pair_output_dir)

        return jsonify(
            {
                "song_a_id": song_a_id,
                "song_b_id": song_b_id,
                "pair_label": f"{song_a_id} -> {song_b_id}",
                "song_a_title": str(load_track_metadata(song_a_id).get("title") or song_a_id),
                "song_b_title": str(load_track_metadata(song_b_id).get("title") or song_b_id),
                "stems": stem_urls,
                "timing": timing,
                "has_existing_transition": all_transitions_rendered(pair_output_dir),
                "existing_styles": existing_styles,
            }
        )

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
    force = bool(payload.get("force", False))

    if not song_a_id or not song_b_id:
        return jsonify({"error": "song_a_id and song_b_id are required."}), 400

    if style_name not in STYLE_NAMES:
        return jsonify({"error": f"style must be one of {STYLE_NAMES}."}), 400

    try:
        process_track(song_a_id)
        process_track(song_b_id)

        pair_output_dir = OUTPUTS_DIR / f"{song_a_id}_to_{song_b_id}"

        if force or not all_transitions_rendered(pair_output_dir):
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
            "styles": build_existing_style_payloads(pair_output_dir),
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
