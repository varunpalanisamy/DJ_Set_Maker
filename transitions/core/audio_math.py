"""BPM math, beat indexing, timestamp utilities, and checkpoint builders."""

from __future__ import annotations

import math


def bpm_diff_ratio(bpm_a: float, bpm_b: float) -> float:
    """Return the relative BPM gap between two BPM values."""
    if bpm_a <= 0 or bpm_b <= 0:
        return 0.0
    return abs(bpm_a - bpm_b) / max(abs(bpm_a), abs(bpm_b))


def calculate_local_bpm(metadata: dict, start_time: float, end_time: float) -> float:
    """Calculate BPM from beat times inside a specific time window."""
    beat_times = [
        float(beat_time)
        for beat_time in metadata.get("beat_times", [])
        if start_time <= float(beat_time) <= end_time
    ]
    if len(beat_times) < 2:
        return float(metadata.get("bpm") or 0.0)

    avg_interval = (beat_times[-1] - beat_times[0]) / (len(beat_times) - 1)
    if avg_interval <= 0:
        return float(metadata.get("bpm") or 0.0)
    return 60.0 / avg_interval


def calculate_preceding_local_bpm(metadata: dict, end_time: float, num_beats: int = 16) -> float:
    """Calculate local BPM from the beats immediately preceding a timestamp."""
    beat_times = [
        float(beat_time)
        for beat_time in metadata.get("beat_times", [])
        if float(beat_time) <= end_time
    ]
    if len(beat_times) < 2:
        return float(metadata.get("bpm") or 0.0)

    window = beat_times[-(num_beats + 1) :]
    if len(window) < 2:
        return float(metadata.get("bpm") or 0.0)

    avg_interval = (window[-1] - window[0]) / (len(window) - 1)
    if avg_interval <= 0:
        return float(metadata.get("bpm") or 0.0)
    return 60.0 / avg_interval


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


def scale_warped_timestamp(timestamp_ms: int, stretch_ratio: float) -> int:
    """Convert an original Song B timestamp into warped-audio time."""
    if stretch_ratio <= 0:
        raise ValueError("Stretch ratio must be positive.")
    return int(round(timestamp_ms / stretch_ratio))


def scale_original_duration(warped_duration_ms: int, stretch_ratio: float) -> int:
    """Convert a warped duration back into the source-audio duration needed before warping."""
    if stretch_ratio <= 0:
        raise ValueError("Stretch ratio must be positive.")
    return int(round(warped_duration_ms * stretch_ratio))


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


def get_effective_bpm_match(bpm_a: float, bpm_b: float) -> tuple[str, float, float]:
    """Choose the closest standard/half-time/double-time interpretation for Song A."""
    if bpm_a <= 0 or bpm_b <= 0:
        raise ValueError("BPM values must be positive.")

    candidates = (
        ("Standard", bpm_a, 1.0),
        ("Double-Time", bpm_a * 2.0, 2.0),
        ("Half-Time", bpm_a / 2.0, 0.5),
    )
    mode, effective_bpm_a, beat_factor = min(candidates, key=lambda item: abs(item[1] - bpm_b))
    return mode, effective_bpm_a, beat_factor


def count_beats_in_window(metadata: dict, start_time: float, end_time: float) -> int:
    """Count beats in a transition window using beat metadata when available."""
    beat_times = [
        float(beat_time)
        for beat_time in metadata.get("beat_times", [])
        if start_time <= float(beat_time) <= end_time
    ]
    if len(beat_times) >= 2:
        return len(beat_times) - 1

    duration_ms = max(0.0, (end_time - start_time) * 1000.0)
    bpm = float(metadata.get("bpm") or 0.0)
    if bpm <= 0:
        return 0
    return max(1, int(round((duration_ms / 60000.0) * bpm)))


def get_beat_index_for_time(metadata: dict, timestamp_sec: float) -> int:
    """Return the nearest beat index for a timestamp."""
    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    if not beat_times:
        return 0
    return min(range(len(beat_times)), key=lambda index: abs(beat_times[index] - timestamp_sec))


def get_duration_of_beats(metadata: dict, start_beat_index: int, beat_count: int) -> float:
    """Return the physical duration in seconds for a span of beats."""
    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    if beat_count <= 0:
        return 0.0
    if 0 <= start_beat_index and (start_beat_index + beat_count) < len(beat_times):
        return beat_times[start_beat_index + beat_count] - beat_times[start_beat_index]

    bpm = float(metadata.get("bpm") or 0.0)
    if bpm <= 0:
        return 0.0
    return beat_count * (60.0 / bpm)


def get_duration_of_virtual_beats(
    metadata: dict,
    start_beat_index: int,
    beat_count: int,
    beat_factor: float,
) -> float:
    """Return the duration for a beat span after optional half/double-time reinterpretation."""
    if beat_factor <= 0:
        raise ValueError("Beat factor must be positive.")
    adjusted_beat_count = max(1, int(round(beat_count / beat_factor)))
    return get_duration_of_beats(metadata, start_beat_index, adjusted_beat_count)


def get_beat_timestamp(metadata: dict, beat_index: int) -> float:
    """Return the timestamp for a beat index, with BPM fallback if needed."""
    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    if beat_times and 0 <= beat_index < len(beat_times):
        return beat_times[beat_index]
    if beat_times:
        bpm = float(metadata.get("bpm") or 0.0)
        if bpm > 0:
            extra_beats = max(0, beat_index - (len(beat_times) - 1))
            return beat_times[-1] + (extra_beats * (60.0 / bpm))
        return beat_times[-1]
    return 0.0


def build_beat_checkpoint_ms(
    metadata: dict,
    start_beat_index: int,
    beat_count: int,
    checkpoint_beats: int = 4,
) -> list[int]:
    """Build relative checkpoint times in ms at fixed beat intervals."""
    beat_times = [float(beat_time) for beat_time in metadata.get("beat_times", [])]
    total_duration_ms = int(round(get_duration_of_beats(metadata, start_beat_index, beat_count) * 1000.0))
    if total_duration_ms <= 0:
        return [0, 1]

    if not beat_times or start_beat_index >= len(beat_times):
        steps = max(1, math.ceil(beat_count / checkpoint_beats))
        return [int(round(total_duration_ms * step / steps)) for step in range(steps + 1)]

    checkpoints = [0]
    start_time = beat_times[start_beat_index]
    for offset in range(checkpoint_beats, beat_count, checkpoint_beats):
        beat_index = start_beat_index + offset
        if beat_index < len(beat_times):
            checkpoints.append(int(round((beat_times[beat_index] - start_time) * 1000.0)))
        else:
            checkpoints.append(int(round(total_duration_ms * offset / beat_count)))
    checkpoints.append(total_duration_ms)

    deduped: list[int] = []
    for checkpoint in checkpoints:
        if not deduped or checkpoint > deduped[-1]:
            deduped.append(checkpoint)
    if deduped[-1] != total_duration_ms:
        deduped.append(total_duration_ms)
    return deduped


def build_master_ramp_checkpoint_ms(
    transition_beats: int,
    start_bpm: float,
    end_bpm: float,
    checkpoint_beats: int = 4,
) -> list[int]:
    """Build target checkpoint times for a smooth BPM ramp across the transition beats."""
    if transition_beats <= 0:
        return [0, 1]
    if start_bpm <= 0 or end_bpm <= 0:
        raise ValueError("BPM values must be positive.")

    def cumulative_minutes(beat_offset: int) -> float:
        progress = beat_offset / transition_beats
        if abs(end_bpm - start_bpm) < 1e-9:
            return beat_offset / start_bpm
        bpm_at_progress = start_bpm + ((end_bpm - start_bpm) * progress)
        return transition_beats * math.log(bpm_at_progress / start_bpm) / (end_bpm - start_bpm)

    checkpoints = [0]
    for beat_offset in range(checkpoint_beats, transition_beats, checkpoint_beats):
        checkpoints.append(int(round(cumulative_minutes(beat_offset) * 60000.0)))
    checkpoints.append(int(round(cumulative_minutes(transition_beats) * 60000.0)))

    deduped: list[int] = []
    for checkpoint in checkpoints:
        if not deduped or checkpoint > deduped[-1]:
            deduped.append(checkpoint)
    if len(deduped) == 1:
        deduped.append(deduped[0] + 1)
    return deduped


def build_virtual_beat_checkpoint_ms(
    metadata: dict,
    start_beat_index: int,
    beat_count: int,
    beat_factor: float,
    checkpoint_beats: int = 4,
) -> list[int]:
    """Build checkpoint times after applying a half/double-time interpretation."""
    if beat_factor <= 0:
        raise ValueError("Beat factor must be positive.")

    adjusted_beat_count = max(1, int(round(beat_count / beat_factor)))
    adjusted_checkpoint_beats = max(1, int(round(checkpoint_beats / beat_factor)))
    return build_beat_checkpoint_ms(
        metadata=metadata,
        start_beat_index=start_beat_index,
        beat_count=adjusted_beat_count,
        checkpoint_beats=adjusted_checkpoint_beats,
    )


def build_ramp_debug_rows(
    checkpoint_ms: list[int],
    start_bpm: float,
    end_bpm: float,
    checkpoint_beats: int = 4,
) -> list[str]:
    """Build human-readable checkpoint debug lines for the gradual ramp."""
    if len(checkpoint_ms) < 2:
        return []

    rows: list[str] = []
    total_segments = len(checkpoint_ms) - 1
    total_beats = total_segments * checkpoint_beats
    for index in range(total_segments):
        start_beat = index * checkpoint_beats
        end_beat = min(total_beats, (index + 1) * checkpoint_beats)
        start_progress = start_beat / total_beats if total_beats else 0.0
        end_progress = end_beat / total_beats if total_beats else 1.0
        bpm_start = start_bpm + ((end_bpm - start_bpm) * start_progress)
        bpm_end = start_bpm + ((end_bpm - start_bpm) * end_progress)
        rows.append(
            f"[Ramp] Beats {start_beat:02d}-{end_beat:02d}: "
            f"{checkpoint_ms[index]}ms -> {checkpoint_ms[index + 1]}ms | "
            f"BPM {bpm_start:.2f} -> {bpm_end:.2f}"
        )
    return rows


def calculate_master_transition_duration_ms(
    transition_beats: int,
    start_bpm: float,
    end_bpm: float,
) -> int:
    """Calculate the shared target duration for a linear BPM ramp across a beat count."""
    if transition_beats <= 0:
        raise ValueError("Transition beat count must be positive.")
    if start_bpm <= 0 or end_bpm <= 0:
        raise ValueError("BPM values must be positive.")

    if abs(end_bpm - start_bpm) < 1e-9:
        minutes = transition_beats / start_bpm
    else:
        minutes = transition_beats * math.log(end_bpm / start_bpm) / (end_bpm - start_bpm)
    return max(1, int(round(minutes * 60000.0)))
