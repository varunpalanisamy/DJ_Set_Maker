"""Pure pydub helpers for sample-rate alignment and segment operations."""

from __future__ import annotations

import math

from pydub import AudioSegment


MASTER_TRANSITION_SAMPLE_RATE = 44100
MICRO_FADE_MS = 2
STEM_NAMES = ("vocals", "drums", "bass", "other")


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


def overlay_stems(stems: dict[str, AudioSegment]) -> AudioSegment:
    """Overlay all stems into a single mix."""
    stems = {stem_name: standardize_audiosegment(stem) for stem_name, stem in stems.items()}
    target_length = max(len(stem) for stem in stems.values())
    padded_stems = [pad_to_length(stem, target_length) for stem in stems.values()]

    mix = padded_stems[0]
    for stem in padded_stems[1:]:
        mix = mix.overlay(stem)
    return mix
