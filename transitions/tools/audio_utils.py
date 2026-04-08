"""Pure pydub helpers for sample-rate alignment and segment operations."""

from __future__ import annotations

import math

from pydub import AudioSegment
from pydub.effects import high_pass_filter


MASTER_TRANSITION_SAMPLE_RATE = 44100
MICRO_FADE_MS = 2
STEM_NAMES = ("vocals", "drums", "bass", "other")
OVERLAY_HEADROOM_DB = 4.0
PEAK_CEILING_DBFS = -0.1
LOW_END_COLLISION_THRESHOLD_DBFS = -1.5
LOW_END_ACTIVE_THRESHOLD_DBFS = -10.0


def standardize_audiosegment(segment: AudioSegment) -> AudioSegment:
    """Normalize sample rate for stable overlays and appends."""
    return segment.set_frame_rate(MASTER_TRANSITION_SAMPLE_RATE)


def apply_micro_fades(segment: AudioSegment, fade_ms: int = MICRO_FADE_MS) -> AudioSegment:
    """Suppress boundary clicks with tiny fades at segment edges."""
    if len(segment) <= 0:
        return segment
    safe_fade_ms = min(fade_ms, len(segment) // 2 if len(segment) > 1 else 1)
    safe_fade_ms = max(1, safe_fade_ms)
    return segment.fade_in(safe_fade_ms).fade_out(safe_fade_ms)


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


def apply_high_pass(segment: AudioSegment, cutoff_hz: int = 250) -> AudioSegment:
    """Apply a high-pass filter to reduce muddy low-end buildup."""
    if len(segment) == 0:
        return segment
    return high_pass_filter(segment, cutoff_hz)


def safe_max_dbfs(segment: AudioSegment) -> float:
    """Return a finite max dBFS value for a segment."""
    if len(segment) == 0:
        return float("-inf")
    value = float(segment.max_dBFS)
    if math.isinf(value):
        return float("-inf")
    return value


def protect_from_clipping(segment: AudioSegment, ceiling_dbfs: float = PEAK_CEILING_DBFS) -> AudioSegment:
    """Scale a segment down if its peak exceeds the target ceiling."""
    if len(segment) == 0:
        return segment
    max_dbfs = safe_max_dbfs(segment)
    if math.isinf(max_dbfs):
        return segment
    if max_dbfs <= ceiling_dbfs:
        return segment
    return segment.apply_gain(ceiling_dbfs - max_dbfs)


def apply_gain_to_region(
    segment: AudioSegment,
    start_ms: int,
    end_ms: int,
    gain_db: float,
) -> AudioSegment:
    """Apply gain to a specific region without affecting the rest of the segment."""
    if len(segment) == 0 or end_ms <= start_ms:
        return segment
    start_ms = max(0, int(start_ms))
    end_ms = min(len(segment), int(end_ms))
    if end_ms <= start_ms:
        return segment
    return segment[:start_ms] + segment[start_ms:end_ms].apply_gain(gain_db) + segment[end_ms:]


def overlay_segments_raw(segments: list[AudioSegment]) -> AudioSegment:
    """Overlay segments without adding headroom or peak protection."""
    if not segments:
        return AudioSegment.silent(duration=0, frame_rate=MASTER_TRANSITION_SAMPLE_RATE)
    standardized = [standardize_audiosegment(segment) for segment in segments]
    target_length = max(len(segment) for segment in standardized)
    padded = [pad_to_length(segment, target_length) for segment in standardized]
    mix = padded[0]
    for segment in padded[1:]:
        mix = mix.overlay(segment)
    return mix


def detect_low_end_collision(
    song_a_low: AudioSegment,
    song_b_low: AudioSegment,
    threshold_dbfs: float = LOW_END_COLLISION_THRESHOLD_DBFS,
    active_dbfs: float = LOW_END_ACTIVE_THRESHOLD_DBFS,
) -> bool:
    """Return True when both low-end layers are active and their sum is peaking too hot."""
    song_a_low = standardize_audiosegment(song_a_low)
    song_b_low = standardize_audiosegment(song_b_low)
    combined = overlay_segments_raw([song_a_low, song_b_low])
    return (
        safe_max_dbfs(song_a_low) >= active_dbfs
        and safe_max_dbfs(song_b_low) >= active_dbfs
        and safe_max_dbfs(combined) >= threshold_dbfs
    )


def overlay_with_headroom(
    base: AudioSegment,
    incoming: AudioSegment,
    position: int = 0,
    headroom_db: float = OVERLAY_HEADROOM_DB,
) -> AudioSegment:
    """Overlay two song layers with shared gain reduction to create headroom."""
    base = standardize_audiosegment(base)
    incoming = standardize_audiosegment(incoming)
    if len(incoming) == 0:
        return protect_from_clipping(base)

    overlay_position = max(0, int(position))
    padded_base = pad_to_length(base, max(len(base), overlay_position + len(incoming)))
    overlap_mix = padded_base.apply_gain(-(headroom_db / 2.0)).overlay(
        incoming.apply_gain(-(headroom_db / 2.0)),
        position=overlay_position,
    )
    return protect_from_clipping(overlap_mix)


def overlay_stems(stems: dict[str, AudioSegment]) -> AudioSegment:
    """Overlay all stems into a single mix."""
    stems = {stem_name: standardize_audiosegment(stem) for stem_name, stem in stems.items()}
    target_length = max(len(stem) for stem in stems.values())
    padded_stems = [pad_to_length(stem, target_length).apply_gain(-3.0) for stem in stems.values()]

    mix = padded_stems[0]
    for stem in padded_stems[1:]:
        mix = mix.overlay(stem)
    return protect_from_clipping(mix)
