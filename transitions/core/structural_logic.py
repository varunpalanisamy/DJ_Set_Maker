"""Metadata loading, tempo-zone analysis, and structural entry/exit selection."""

from __future__ import annotations

import json
from pathlib import Path

from transitions.core.audio_math import (
    bpm_diff_ratio,
    calculate_local_bpm,
    calculate_preceding_local_bpm,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
METADATA_DIR = PROJECT_ROOT / "metadata"
MAX_PICKUP_BEATS = 2


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
                    "start_beat_index": segment.get("start_beat_index"),
                    "end_beat_index": segment.get("end_beat_index"),
                    "aligned_start_time": start_time,
                    "aligned_end_time": end_time,
                }
            )
        else:
            if merged_segments[-1].get("start_beat_index") is None:
                merged_segments[-1]["start_beat_index"] = segment.get("start_beat_index")
            merged_segments[-1]["end_beat_index"] = segment.get("end_beat_index")
            merged_segments[-1]["aligned_end_time"] = end_time

    return merged_segments


def align_segment_end_to_phrase_boundary(
    segment: dict, metadata: dict, phrase_beats: int = 4
) -> float:
    """Step an off-grid segment ending back to the nearest clean phrase boundary."""
    end_beat_index = segment.get("end_beat_index")
    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    fallback_time = float(segment.get("aligned_end_time", 0.0))
    if end_beat_index is None or not beat_times:
        return fallback_time

    end_beat_index = int(end_beat_index)
    if end_beat_index < phrase_beats:
        return fallback_time
    if end_beat_index % phrase_beats == 0 and end_beat_index < len(beat_times):
        return beat_times[end_beat_index]

    previous_boundary = (end_beat_index // phrase_beats) * phrase_beats
    next_boundary = previous_boundary + phrase_beats

    if next_boundary < len(beat_times):
        print(
            f"[Logic] Off-grid segment ending at beat {end_beat_index}. "
            f"Snapping forward to beat {next_boundary} for phrase alignment."
        )
        return beat_times[next_boundary]

    if previous_boundary > 0 and previous_boundary < len(beat_times):
        print(
            f"[Logic] Off-grid segment ending at beat {end_beat_index}. "
            f"Forward boundary unavailable, snapping backward to beat {previous_boundary} "
            f"for phrase alignment."
        )
        return beat_times[previous_boundary]

    return fallback_time


def detect_tempo_zones(metadata: dict) -> list[dict]:
    """Detect stable BPM zones and split only on major tempo changes."""
    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    minimum_beats = 16
    if len(beat_times) < minimum_beats + 1:
        return []

    stable_windows: list[dict] = []
    for start_index in range(len(beat_times) - minimum_beats):
        window = beat_times[start_index : start_index + minimum_beats + 1]
        intervals = [window[index + 1] - window[index] for index in range(minimum_beats)]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval <= 0:
            continue
        if any(abs(interval - avg_interval) / avg_interval > 0.02 for interval in intervals):
            continue
        stable_windows.append(
            {
                "start_time": beat_times[start_index],
                "end_time": beat_times[start_index + minimum_beats],
                "bpm": 60.0 / avg_interval,
            }
        )

    if not stable_windows:
        return []

    zones: list[dict] = []
    current_zone = stable_windows[0].copy()
    for window in stable_windows[1:]:
        if bpm_diff_ratio(window["bpm"], current_zone["bpm"]) <= 0.02:
            current_zone["end_time"] = window["end_time"]
            current_zone["bpm"] = (current_zone["bpm"] + window["bpm"]) / 2.0
            continue
        if bpm_diff_ratio(window["bpm"], current_zone["bpm"]) > 0.15:
            zones.append(current_zone)
            current_zone = window.copy()

    zones.append(current_zone)
    return zones


def get_major_tempo_zones(
    metadata: dict,
    minimum_beats: int = 64,
    minimum_duration_sec: float = 30.0,
    split_threshold: float = 0.05,
    split_threshold_bpm: float = 4.0,
) -> list[dict]:
    """Return substantial stable tempo zones, ignoring short outro fluctuations."""
    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    window_beats = 16
    if len(beat_times) < window_beats + 1:
        duration_sec = float(metadata.get("duration_sec") or 0.0)
        return [{"start_time": 0.0, "end_time": duration_sec, "bpm": float(metadata.get("bpm") or 0.0)}]

    stable_windows: list[dict] = []
    for start_index in range(len(beat_times) - window_beats):
        window = beat_times[start_index : start_index + window_beats + 1]
        intervals = [window[index + 1] - window[index] for index in range(window_beats)]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval <= 0:
            continue
        if any(abs(interval - avg_interval) / avg_interval > 0.02 for interval in intervals):
            continue
        stable_windows.append(
            {
                "start_time": beat_times[start_index],
                "end_time": beat_times[start_index + window_beats],
                "bpm": 60.0 / avg_interval,
            }
        )

    if not stable_windows:
        duration_sec = float(metadata.get("duration_sec") or beat_times[-1])
        return [{"start_time": 0.0, "end_time": duration_sec, "bpm": float(metadata.get("bpm") or 0.0)}]

    zones: list[dict] = []
    current_zone = stable_windows[0].copy()
    for window in stable_windows[1:]:
        bpm_gap = abs(float(window["bpm"]) - float(current_zone["bpm"]))
        if (
            bpm_diff_ratio(window["bpm"], current_zone["bpm"]) <= split_threshold
            and bpm_gap < split_threshold_bpm
        ):
            current_zone["end_time"] = window["end_time"]
            current_zone["bpm"] = (current_zone["bpm"] + window["bpm"]) / 2.0
            continue
        zones.append(current_zone)
        current_zone = window.copy()
    zones.append(current_zone)

    major_zones: list[dict] = []
    for zone in zones:
        zone_start = float(zone["start_time"])
        zone_end = float(zone["end_time"])
        zone_beats = [beat_time for beat_time in beat_times if zone_start <= beat_time <= zone_end]
        zone_beat_count = max(0, len(zone_beats) - 1)
        zone_duration = max(0.0, zone_end - zone_start)
        if zone_beat_count >= minimum_beats or zone_duration >= minimum_duration_sec:
            major_zones.append(zone)

    if major_zones:
        return major_zones

    longest_zone = max(zones, key=lambda zone: float(zone["end_time"]) - float(zone["start_time"]))
    return [longest_zone]


def get_final_stable_zone(metadata: dict) -> dict:
    """Return the last substantial tempo zone in the track."""
    major_zones = get_major_tempo_zones(metadata)
    return major_zones[-1]


def has_major_tempo_shift(
    metadata: dict,
    threshold: float = 0.05,
    threshold_bpm: float = 4.0,
) -> bool:
    """Return True when the track contains multiple substantial tempo zones."""
    major_zones = get_major_tempo_zones(metadata)
    if len(major_zones) < 2:
        return False

    for previous_zone, next_zone in zip(major_zones, major_zones[1:]):
        previous_bpm = float(previous_zone["bpm"])
        next_bpm = float(next_zone["bpm"])
        if bpm_diff_ratio(previous_bpm, next_bpm) > threshold or abs(previous_bpm - next_bpm) >= threshold_bpm:
            return True
    return False


def select_exit_chorus_block_with_reason(metadata: dict) -> tuple[dict | None, str | None]:
    """Select the chorus block and explain why it was chosen."""
    merged_segments = merge_consecutive_segments(metadata)
    if has_major_tempo_shift(metadata):
        final_zone = get_final_stable_zone(metadata)
        zone_start = float(final_zone["start_time"])
        chorus_blocks = [
            segment
            for segment in merged_segments
            if segment["label"] == "chorus" and float(segment["aligned_start_time"]) >= zone_start
        ]
        if chorus_blocks:
            return (
                chorus_blocks[-1],
                (
                    "Detected a beat switch, filtered to chorus blocks inside the final tempo zone, "
                    "and used the last chorus in that zone."
                ),
            )
        return None, None

    chorus_blocks = [segment for segment in merged_segments if segment["label"] == "chorus"]
    if not chorus_blocks:
        return None, None

    if len(chorus_blocks) == 1:
        return chorus_blocks[0], "Found only one chorus block in the song, so that chorus was used."

    if len(chorus_blocks) == 2:
        return (
            chorus_blocks[1],
            (
                "Found exactly 2 chorus blocks in the song. "
                "Applied the two-chorus rule and picked the second chorus directly "
                "instead of using the standard minus-1 rule."
            ),
        )

    default_target_index = len(chorus_blocks) - 2
    default_target_block = chorus_blocks[default_target_index]

    eligible_override_blocks = chorus_blocks[1:default_target_index]
    for segment in reversed(eligible_override_blocks):
        if (segment["aligned_end_time"] - segment["aligned_start_time"]) >= 30.0:
            chosen_index = chorus_blocks.index(segment) + 1
            default_index = default_target_index + 1
            return (
                segment,
                (
                    f"Checked {len(chorus_blocks)} chorus blocks. The default rule would use chorus "
                    f"{default_index} (second-to-last), but an earlier eligible 30+ second chorus "
                    f"block was found at chorus {chosen_index}, so that override was used. "
                    "The first chorus was ignored for the override."
                ),
            )

    return (
        default_target_block,
        (
            f"Checked {len(chorus_blocks)} chorus blocks. The default rule picked chorus "
            f"{default_target_index + 1} because it is the second-to-last chorus block. "
            "No eligible 30+ second chorus before that target overrode it."
        ),
    )


def select_exit_chorus_block(metadata: dict) -> dict | None:
    """Select the chorus block using beat-switch or standard single-BPM rules."""
    selected_chorus, _ = select_exit_chorus_block_with_reason(metadata)
    return selected_chorus


def get_optimal_exit_time(metadata: dict) -> float:
    """Pick Song A's exit point from merged structural blocks."""
    selected_chorus = select_exit_chorus_block(metadata)
    if selected_chorus is not None:
        if has_major_tempo_shift(metadata):
            return float(selected_chorus["aligned_start_time"])
        return align_segment_end_to_phrase_boundary(selected_chorus, metadata)

    merged_segments = merge_consecutive_segments(metadata)
    if has_major_tempo_shift(metadata):
        final_zone = get_final_stable_zone(metadata)
        zone_start = float(final_zone["start_time"])
        verses = [
            segment
            for segment in merged_segments
            if segment["label"] == "verse" and float(segment["aligned_start_time"]) >= zone_start
        ]
    else:
        verses = [segment for segment in merged_segments if segment["label"] == "verse"]
    if verses:
        return float(verses[-1]["aligned_end_time"])

    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    if beat_times:
        return float(beat_times[-1])

    if metadata.get("duration_sec") is not None:
        return float(metadata["duration_sec"])

    track_id = metadata.get("_resolved_track_id", metadata.get("track_id", "unknown"))
    raise ValueError(f"Could not determine an exit point for '{track_id}'.")


def get_exit_chorus_block(metadata: dict) -> dict | None:
    """Return the chorus block that should feed Song A's transition loop."""
    return select_exit_chorus_block(metadata)


def get_song_entry_time(metadata: dict) -> float:
    """Find the first internally consistent 16-beat block and use it as Song B entry."""
    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    merged_segments = merge_consecutive_segments(metadata)
    global_bpm = float(metadata.get("bpm") or 0.0)

    intro_segments = [
        segment for segment in metadata.get("segments", []) if str(segment.get("label", "")).lower() == "intro"
    ]
    earliest_intro_time = (
        float(intro_segments[0]["aligned_start_time"])
        if intro_segments
        else next(
            (
                float(segment["aligned_start_time"])
                for segment in merged_segments
                if segment["label"] in {"start", "intro"}
            ),
            float(beat_times[0]) if beat_times else 0.0,
        )
    )
    final_intro_end = (
        float(intro_segments[-1]["aligned_end_time"])
        if intro_segments
        else next(
            (
                float(segment["aligned_end_time"])
                for segment in merged_segments
                if segment["label"] in {"start", "intro"}
            ),
            earliest_intro_time,
        )
    )
    slow_start_detected = False

    if global_bpm > 0 and len(beat_times) >= 33:
        first_32_beats_end = beat_times[32]
        opening_bpm = calculate_local_bpm(metadata, beat_times[0], first_32_beats_end)
        if bpm_diff_ratio(opening_bpm, global_bpm) <= 0.05:
            print(f"[Pipeline] Entry locked at {earliest_intro_time:.2f}s (Global BPM stable)")
            return earliest_intro_time
        slow_start_detected = opening_bpm <= (global_bpm * 0.85)
        print("[Pipeline] START DETECTED AS UNSTABLE/SLOW. Initiating stabilization scan...")

    stable_blocks: list[dict] = []
    if len(beat_times) >= 17:
        for start_index in range(len(beat_times) - 16):
            intervals = [
                beat_times[start_index + offset + 1] - beat_times[start_index + offset]
                for offset in range(16)
            ]
            avg_interval = sum(intervals) / len(intervals)
            if avg_interval <= 0:
                continue
            if any(abs(interval - avg_interval) / avg_interval > 0.05 for interval in intervals):
                continue
            stable_blocks.append(
                {
                    "start_index": start_index,
                    "start_time": beat_times[start_index],
                    "bpm": 60.0 / avg_interval,
                }
            )

    if stable_blocks:
        chosen_block = stable_blocks[0]
        if global_bpm > 0 and chosen_block["bpm"] <= (global_bpm * 0.85):
            slow_start_detected = True
            print(
                f"[Pipeline] SLOW INTRO DETECTED: Found stable block at "
                f"{chosen_block['start_time']:.2f}s with {chosen_block['bpm']:.2f} BPM "
                f"(Global BPM is {global_bpm:.2f}). Searching for higher energy..."
            )
        for later_block in stable_blocks[1:]:
            if later_block["start_time"] > max(45.0, final_intro_end + 8.0):
                break
            if later_block["bpm"] >= (global_bpm * 0.95) or later_block["bpm"] > chosen_block["bpm"] * 1.10:
                print(
                    f"[Pipeline] SKIPPING SLOW SECTION: Jumping from "
                    f"{chosen_block['start_time']:.2f}s ({chosen_block['bpm']:.2f} BPM) "
                    f"to {later_block['start_time']:.2f}s ({later_block['bpm']:.2f} BPM) "
                    f"to match track energy."
                )
                chosen_block = later_block
                break

        entry_time = float(chosen_block["start_time"])
        if slow_start_detected:
            if entry_time - beat_times[0] > 1.0:
                print(
                    f"[Pipeline] REMOVING INTRO SECTION: Advancing entry from "
                    f"{beat_times[0]:.2f}s to {entry_time:.2f}s to skip the slow intro."
                )
        elif len(intro_segments) >= 2:
            last_intro_start = float(intro_segments[-1]["aligned_start_time"])
            last_intro_end = float(intro_segments[-1]["aligned_end_time"])
            if entry_time >= last_intro_end:
                entry_time = last_intro_start
        if entry_time - beat_times[0] > 5.0:
            print(f"[Pipeline] SLOW INTRO REMOVED. Entry point locked at {entry_time:.2f}s.")
        print(f"[Pipeline] Entry locked at {entry_time:.2f}s (BPM stabilized)")
        return entry_time

    if intro_segments:
        print(
            f"[Pipeline] WARNING: No stabilization found. Falling back to absolute start at "
            f"{earliest_intro_time:.2f}s."
        )
        return earliest_intro_time

    for segment in merged_segments:
        if segment["label"] in {"start", "intro"}:
            print(
                f"[Pipeline] WARNING: No stabilization found. Falling back to absolute start at "
                f"{float(segment['aligned_start_time']):.2f}s."
            )
            return float(segment["aligned_start_time"])

    for segment in merged_segments:
        if segment["label"] in {"verse", "chorus"}:
            return float(segment["aligned_start_time"])

    segments = metadata.get("segments", [])
    if segments and "aligned_start_time" in segments[0]:
        print(
            f"[Pipeline] WARNING: No stabilization found. Falling back to absolute start at "
            f"{float(segments[0]['aligned_start_time']):.2f}s."
        )
        return float(segments[0]["aligned_start_time"])

    return 0.0


def get_song_b_drop_time(metadata: dict, entry_time: float | None = None) -> float:
    """Return the structural drop point for Song B after its intro/start blocks."""
    if entry_time is None:
        entry_time = get_song_entry_time(metadata)
    for segment in merge_consecutive_segments(metadata):
        label = segment["label"]
        if label not in {"verse", "chorus"}:
            continue
        drop_time = float(segment["aligned_start_time"])
        if drop_time > entry_time:
            return drop_time

    beat_times = metadata.get("beat_times", [])
    for beat_time in beat_times:
        if float(beat_time) > entry_time:
            return float(beat_time)

    duration_sec = metadata.get("duration_sec")
    if duration_sec is not None:
        return float(duration_sec)

    track_id = metadata.get("_resolved_track_id", metadata.get("track_id", "unknown"))
    raise ValueError(f"Could not determine Song B drop point for '{track_id}'.")


def calculate_pickup_ms(metadata: dict, entry_time_sec: float, max_pickup_beats: int = MAX_PICKUP_BEATS) -> int:
    """Return a capped preroll window before the structural entry downbeat."""
    if entry_time_sec <= 0 or max_pickup_beats <= 0:
        return 0

    local_bpm = calculate_preceding_local_bpm(metadata, entry_time_sec, num_beats=16)
    if local_bpm <= 0:
        local_bpm = float(metadata.get("bpm") or 0.0)
    if local_bpm <= 0:
        return 0

    max_pickup_ms = int(round((60000.0 / local_bpm) * max_pickup_beats))
    available_preroll_ms = int(round(entry_time_sec * 1000.0))
    return max(0, min(max_pickup_ms, available_preroll_ms))


def calculate_song_a_pickup_ms(
    metadata: dict,
    target_start_time_sec: float,
    max_pickup_beats: int = MAX_PICKUP_BEATS,
) -> int:
    """Return a capped cue pickup window before Song A's looped chorus downbeat."""
    return calculate_pickup_ms(
        metadata=metadata,
        entry_time_sec=target_start_time_sec,
        max_pickup_beats=max_pickup_beats,
    )
