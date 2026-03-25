#!/usr/bin/env python3
"""Render BPM-matched DJ transitions for a pair of tracks."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydub import AudioSegment


PROJECT_ROOT = Path(__file__).resolve().parent
METADATA_DIR = PROJECT_ROOT / "metadata"
STEMS_DIR = PROJECT_ROOT / "stems"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
STEM_NAMES = ("vocals", "drums", "bass", "other")
STYLE_SPECS = (
    ("Style_A", "Vocal Cut"),
    ("Style_B", "Loop and Fade"),
    ("Style_C", "Instrumental Bed"),
)


def load_metadata(track_id: str) -> dict:
    """Load metadata for one track ID."""
    metadata_path = METADATA_DIR / f"{track_id}.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

    with metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)

    if "bpm" not in metadata:
        raise ValueError(f"Metadata for '{track_id}' is missing a 'bpm' value.")
    if "segments" not in metadata or not isinstance(metadata["segments"], list):
        raise ValueError(f"Metadata for '{track_id}' is missing a valid 'segments' list.")

    metadata["_resolved_track_id"] = track_id
    return metadata


def load_stems(track_id: str) -> dict[str, AudioSegment]:
    """Load all stems for a track ID."""
    return load_stems_from_dir(STEMS_DIR / track_id)


def load_stems_from_dir(stem_dir: Path) -> dict[str, AudioSegment]:
    """Load stems from a concrete directory."""
    if not stem_dir.is_dir():
        raise FileNotFoundError(f"Stem directory not found: {stem_dir}")

    stems: dict[str, AudioSegment] = {}
    for stem_name in STEM_NAMES:
        stem_path = next(
            (
                candidate
                for candidate in (stem_dir / f"{stem_name}.wav", stem_dir / f"{stem_name}.mp3")
                if candidate.is_file()
            ),
            None,
        )
        if stem_path is None:
            raise FileNotFoundError(f"Missing stem file for '{stem_name}' in {stem_dir}")
        stems[stem_name] = AudioSegment.from_file(stem_path)

    return stems


def merge_consecutive_segments(metadata: dict) -> list[dict]:
    """Merge adjacent structural segments with the same label."""
    merged_segments: list[dict] = []
    for segment in metadata.get("segments", []):
        label = str(segment.get("label", "")).lower()
        start_time = float(segment.get("aligned_start_time", 0.0))
        end_time = float(segment.get("aligned_end_time", start_time))

        if not merged_segments or merged_segments[-1]["label"] != label:
            merged_segments.append(
                {
                    "label": label,
                    "aligned_start_time": start_time,
                    "aligned_end_time": end_time,
                }
            )
        else:
            merged_segments[-1]["aligned_end_time"] = end_time

    return merged_segments


def get_optimal_exit_time(metadata: dict) -> float:
    """Pick Song A's exit point from merged structural blocks."""
    merged_segments = merge_consecutive_segments(metadata)
    valid_choruses = [
        segment
        for segment in merged_segments
        if segment["label"] == "chorus" and segment["aligned_start_time"] >= 45.0
    ]
    if len(valid_choruses) >= 2:
        return float(valid_choruses[1]["aligned_end_time"])
    if len(valid_choruses) == 1:
        return float(valid_choruses[0]["aligned_end_time"])

    verses = [segment for segment in merged_segments if segment["label"] == "verse"]
    if verses:
        return float(verses[-1]["aligned_end_time"])

    beat_times = metadata.get("beat_times", [])
    if beat_times:
        return float(beat_times[-1])

    if metadata.get("duration_sec") is not None:
        return float(metadata["duration_sec"])

    track_id = metadata.get("_resolved_track_id", metadata.get("track_id", "unknown"))
    raise ValueError(f"Could not determine an exit point for '{track_id}'.")


def get_song_entry_time(metadata: dict) -> float:
    """Use the first beat as Song B's structural entry point."""
    beat_times = metadata.get("beat_times", [])
    if beat_times:
        return float(beat_times[0])

    segments = metadata.get("segments", [])
    if segments and "aligned_start_time" in segments[0]:
        return float(segments[0]["aligned_start_time"])

    return 0.0


def snap_to_nearest_beat(timestamp_ms: int, metadata: dict) -> int:
    """Snap a timestamp to the nearest beat in the metadata."""
    beat_times = metadata.get("beat_times", [])
    if not beat_times:
        return timestamp_ms

    timestamp_sec = timestamp_ms / 1000.0
    nearest_beat_sec = min(beat_times, key=lambda beat_time: abs(float(beat_time) - timestamp_sec))
    return int(round(float(nearest_beat_sec) * 1000.0))


def ms_to_timestamp(milliseconds: int) -> str:
    """Format milliseconds as M:SS.mmm."""
    total_seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}.{ms:03d}"


def silence_like(reference: AudioSegment, duration_ms: int) -> AudioSegment:
    """Create silence matching the format of a reference segment."""
    duration_ms = max(0, int(duration_ms))
    silent = AudioSegment.silent(duration=duration_ms, frame_rate=reference.frame_rate)
    silent = silent.set_channels(reference.channels)
    silent = silent.set_sample_width(reference.sample_width)
    return silent


def pad_to_length(segment: AudioSegment, target_length_ms: int) -> AudioSegment:
    """Pad or trim a segment to the target length."""
    if len(segment) >= target_length_ms:
        return segment[:target_length_ms]
    return segment + silence_like(segment, target_length_ms - len(segment))


def combine_segments(parts: list[AudioSegment], reference: AudioSegment) -> AudioSegment:
    """Concatenate a list of segments."""
    if not parts:
        return silence_like(reference, 0)

    combined = parts[0]
    for part in parts[1:]:
        combined += part
    return combined


def linear_gain_to_db(gain: float) -> float:
    """Convert linear gain to decibels."""
    if gain <= 0:
        return -120.0
    return 20.0 * math.log10(gain)


def loop_to_duration(loop_source: AudioSegment, total_duration_ms: int) -> AudioSegment:
    """Repeat a loop source until it fills the requested duration."""
    if total_duration_ms <= 0:
        return silence_like(loop_source, 0)
    if len(loop_source) == 0:
        return silence_like(loop_source, total_duration_ms)

    loops_needed = max(1, math.ceil(total_duration_ms / len(loop_source)))
    return (loop_source * loops_needed)[:total_duration_ms]


def ensure_tool_available(tool_name: str) -> None:
    """Check that an external tool is available on PATH."""
    if shutil.which(tool_name) is None:
        raise FileNotFoundError(
            f"Required tool '{tool_name}' was not found on PATH. Install it before rendering."
        )


def run_command(command: list[str]) -> None:
    """Run a subprocess command and raise with stderr if it fails."""
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or "").strip() or (exc.stdout or "").strip() or str(exc.returncode)
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{details}") from exc


def scale_warped_timestamp(timestamp_ms: int, stretch_ratio: float) -> int:
    """Convert an original Song B timestamp into warped-audio time."""
    if stretch_ratio <= 0:
        raise ValueError("Stretch ratio must be positive.")
    return int(round(timestamp_ms / stretch_ratio))


def get_warped_beat_ms(bpm_b: float, stretch_ratio: float) -> int:
    """Estimate Song B's beat duration after BPM warping."""
    if bpm_b <= 0:
        raise ValueError("Song B BPM must be positive.")
    original_beat_ms = int(round(60000.0 / bpm_b))
    return scale_warped_timestamp(original_beat_ms, stretch_ratio)


def get_optimal_stretch_ratio(bpm_a: float, bpm_b: float) -> float:
    """Choose the least-destructive standard, double-time, or half-time match."""
    if bpm_a <= 0 or bpm_b <= 0:
        raise ValueError("BPM values must be positive.")

    candidates = (
        ("Standard", bpm_a / bpm_b),
        ("Double-Time", bpm_a / (bpm_b * 2.0)),
        ("Half-Time", bpm_a / (bpm_b / 2.0)),
    )
    _, ratio = min(candidates, key=lambda item: abs(1.0 - item[1]))
    return ratio


def get_stretch_mode(bpm_a: float, bpm_b: float) -> str:
    """Return the selected BPM matching mode label."""
    candidates = (
        ("Standard", bpm_a / bpm_b),
        ("Double-Time", bpm_a / (bpm_b * 2.0)),
        ("Half-Time", bpm_a / (bpm_b / 2.0)),
    )
    mode, _ = min(candidates, key=lambda item: abs(1.0 - item[1]))
    return mode


def warp_song_b_stems(track_id: str, stretch_ratio: float, temp_dir: Path) -> dict[str, AudioSegment]:
    """Warp Song B stems to Song A's BPM using ffmpeg + Rubber Band."""
    ensure_tool_available("ffmpeg")
    ensure_tool_available("rubberband")

    source_dir = STEMS_DIR / track_id
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Stem directory not found: {source_dir}")

    converted_dir = temp_dir / "converted"
    warped_dir = temp_dir / "warped"
    converted_dir.mkdir(parents=True, exist_ok=True)
    warped_dir.mkdir(parents=True, exist_ok=True)

    for stem_name in STEM_NAMES:
        input_path = next(
            (
                candidate
                for candidate in (source_dir / f"{stem_name}.wav", source_dir / f"{stem_name}.mp3")
                if candidate.is_file()
            ),
            None,
        )
        if input_path is None:
            raise FileNotFoundError(f"Missing input stem for warping in {source_dir}: {stem_name}")

        converted_path = converted_dir / f"{stem_name}.wav"
        warped_path = warped_dir / f"{stem_name}.wav"

        print(f"[Warp] Converting Song B stem to WAV: {input_path.name}")
        run_command(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(input_path), str(converted_path)]
        )

        print(f"[Warp] Rubber Band on {stem_name} with tempo ratio {stretch_ratio:.6f}")
        run_command(
            [
                "rubberband",
                "--tempo",
                f"{stretch_ratio:.8f}",
                str(converted_path),
                str(warped_path),
            ]
        )

    return load_stems_from_dir(warped_dir)


def build_song_a_transition_window(
    style_name: str,
    stem_name: str,
    segment: AudioSegment,
    transition_start_ms: int,
    transition_ms: int,
    beat_ms: int,
) -> AudioSegment:
    """Build Song A's outgoing window for one style."""
    original_window = pad_to_length(segment[transition_start_ms:], transition_ms)

    if style_name == "Style_A":
        if stem_name == "vocals":
            return silence_like(segment, transition_ms)
        return original_window.fade_out(transition_ms)

    if style_name == "Style_B":
        loop_length_ms = beat_ms * 8
        loop_start_ms = max(0, transition_start_ms - loop_length_ms)
        loop_source = pad_to_length(segment[loop_start_ms:transition_start_ms], loop_length_ms)
        return loop_to_duration(loop_source, transition_ms).fade_out(transition_ms)

    if style_name == "Style_C":
        if stem_name in {"vocals", "bass"}:
            return silence_like(segment, transition_ms)

        hold_ms = min(beat_ms * 8, transition_ms)
        hold = original_window[:hold_ms]
        fade = original_window[hold_ms:transition_ms]
        if len(fade) > 0:
            fade = fade.fade_out(len(fade))
        return combine_segments([hold, fade], segment)

    raise ValueError(f"Unknown style: {style_name}")


def build_song_b_transition_window(
    style_name: str,
    window: AudioSegment,
    transition_ms: int,
    song_b_beat_ms: int,
) -> AudioSegment:
    """Build Song B's incoming window for one style."""
    if style_name == "Style_A":
        return window.fade_in(transition_ms)

    if style_name == "Style_B":
        attack_ms = max(1, min(250, song_b_beat_ms))
        return window.fade_in(attack_ms)

    if style_name == "Style_C":
        attack_ms = max(1, min(500, song_b_beat_ms * 2))
        start_gain_db = linear_gain_to_db(0.8)
        return window.fade(from_gain=start_gain_db, to_gain=0.0, start=0, duration=attack_ms)

    raise ValueError(f"Unknown style: {style_name}")


def apply_song_a_automation(
    style_name: str,
    stem_name: str,
    segment: AudioSegment,
    transition_start_ms: int,
    transition_ms: int,
    beat_ms: int,
) -> AudioSegment:
    """Apply Song A automation for one style."""
    prefix = segment[:transition_start_ms]
    processed_window = build_song_a_transition_window(
        style_name=style_name,
        stem_name=stem_name,
        segment=segment,
        transition_start_ms=transition_start_ms,
        transition_ms=transition_ms,
        beat_ms=beat_ms,
    )
    return combine_segments([prefix, processed_window], segment)


def apply_song_b_automation(
    style_name: str,
    segment: AudioSegment,
    song_b_entry_ms: int,
    transition_ms: int,
    song_b_beat_ms: int,
) -> AudioSegment:
    """Apply Song B automation for one style."""
    trimmed = segment[song_b_entry_ms:]
    trimmed = pad_to_length(trimmed, max(len(trimmed), transition_ms))
    window = trimmed[:transition_ms]
    suffix = trimmed[transition_ms:]
    processed_window = build_song_b_transition_window(
        style_name=style_name,
        window=window,
        transition_ms=transition_ms,
        song_b_beat_ms=song_b_beat_ms,
    )
    return combine_segments([processed_window, suffix], trimmed)


def overlay_stems(stems: dict[str, AudioSegment]) -> AudioSegment:
    """Overlay all stems into a single mix."""
    target_length = max(len(stem) for stem in stems.values())
    padded_stems = [pad_to_length(stem, target_length) for stem in stems.values()]

    mix = padded_stems[0]
    for stem in padded_stems[1:]:
        mix = mix.overlay(stem)
    return mix


def render_style(
    style_name: str,
    style_label: str,
    stems_a: dict[str, AudioSegment],
    stems_b: dict[str, AudioSegment],
    transition_start_ms: int,
    transition_ms: int,
    song_b_entry_ms: int,
    beat_ms: int,
    song_b_beat_ms: int,
    output_path: Path,
) -> Path:
    """Render one transition style and export it."""
    print(f"[Render] Building {style_name}: {style_label}")

    processed_a = {
        stem_name: apply_song_a_automation(
            style_name=style_name,
            stem_name=stem_name,
            segment=stem_audio,
            transition_start_ms=transition_start_ms,
            transition_ms=transition_ms,
            beat_ms=beat_ms,
        )
        for stem_name, stem_audio in stems_a.items()
    }

    processed_b = {
        stem_name: apply_song_b_automation(
            style_name=style_name,
            segment=stem_audio,
            song_b_entry_ms=song_b_entry_ms,
            transition_ms=transition_ms,
            song_b_beat_ms=song_b_beat_ms,
        )
        for stem_name, stem_audio in stems_b.items()
    }

    mix_a = overlay_stems(processed_a)
    mix_b = overlay_stems(processed_b)
    final_mix = mix_a.overlay(mix_b, position=transition_start_ms)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[Render] Exporting {style_name} to {output_path}")
    final_mix.export(output_path, format="mp3", bitrate="320k")
    return output_path


def render_all_styles(song_a_id: str, song_b_id: str, pair_output_dir: Path) -> list[Path]:
    """Render all transition styles for one adjacent pair of tracks."""
    pair_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Render] Loading metadata for {song_a_id} -> {song_b_id}")
    metadata_a = load_metadata(song_a_id)
    metadata_b = load_metadata(song_b_id)

    bpm_a = float(metadata_a["bpm"])
    bpm_b = float(metadata_b["bpm"])
    stretch_ratio = get_optimal_stretch_ratio(bpm_a, bpm_b)
    stretch_mode = get_stretch_mode(bpm_a, bpm_b)

    original_song_b_entry_ms = int(round(get_song_entry_time(metadata_b) * 1000.0))
    raw_song_a_exit_ms = int(round(get_optimal_exit_time(metadata_a) * 1000.0))

    beat_ms = int(round(60000.0 / bpm_a))
    bar_ms = beat_ms * 4
    transition_ms = beat_ms * 16
    transition_start_ms = snap_to_nearest_beat(raw_song_a_exit_ms, metadata_a)
    song_b_entry_ms = scale_warped_timestamp(original_song_b_entry_ms, stretch_ratio)
    song_b_beat_ms = get_warped_beat_ms(bpm_b, stretch_ratio)

    print(f"[Render] Song A BPM: {bpm_a:.2f}")
    print(f"[Render] Song B BPM: {bpm_b:.2f}")
    print(f"[Render] BPM match mode: {stretch_mode}")
    print(f"[Render] Stretch ratio: {stretch_ratio:.6f}")
    print(f"[Render] 1 beat = {beat_ms} ms | 1 bar = {bar_ms} ms")
    print(f"[Render] Song A exit = {ms_to_timestamp(raw_song_a_exit_ms)}")
    print(f"[Render] Beat-aligned start = {ms_to_timestamp(transition_start_ms)}")
    print(f"[Render] Song B entry (original) = {ms_to_timestamp(original_song_b_entry_ms)}")
    print(f"[Render] Song B entry (warped) = {ms_to_timestamp(song_b_entry_ms)}")

    stems_a = load_stems(song_a_id)
    with tempfile.TemporaryDirectory(prefix=f"{song_a_id}_to_{song_b_id}_", dir=PROJECT_ROOT) as temp_dir_str:
        stems_b = warp_song_b_stems(song_b_id, stretch_ratio, Path(temp_dir_str))

        rendered_paths: list[Path] = []
        for style_name, style_label in STYLE_SPECS:
            output_path = pair_output_dir / f"{style_name}.mp3"
            render_style(
                style_name=style_name,
                style_label=style_label,
                stems_a=stems_a,
                stems_b=stems_b,
                transition_start_ms=transition_start_ms,
                transition_ms=transition_ms,
                song_b_entry_ms=song_b_entry_ms,
                beat_ms=beat_ms,
                song_b_beat_ms=song_b_beat_ms,
                output_path=output_path,
            )
            rendered_paths.append(output_path)
            print(f"[Success] Saved {style_name} to {output_path}")

    return rendered_paths


def main() -> None:
    """CLI entrypoint for manually rendering a single pair by editing args elsewhere."""
    raise SystemExit("Import render_all_styles(...) from main.py instead of running this directly.")


if __name__ == "__main__":
    main()
