"""Style-specific transition routing for Song A and Song B windows."""

from __future__ import annotations

from pydub import AudioSegment

from transitions.tools.audio_utils import (
    combine_segments,
    loop_to_duration,
    pad_to_length,
    silence_like,
    standardize_audiosegment,
)


def build_song_a_loop_window(
    segment: AudioSegment,
    transition_start_ms: int,
    transition_ms: int,
    beat_ms: int,
    chorus_block_ms: tuple[int, int] | None,
) -> AudioSegment:
    """Build the raw looping source window for Song A's transition."""
    if chorus_block_ms is not None:
        chorus_start_ms, chorus_end_ms = chorus_block_ms
        loop_source = segment[max(0, chorus_start_ms) : max(chorus_start_ms, chorus_end_ms)]
    else:
        loop_source = segment[max(0, transition_start_ms - transition_ms) : transition_start_ms]
    loop_source = pad_to_length(loop_source, max(1, len(loop_source)))
    return loop_to_duration(loop_source, transition_ms)


def apply_song_a_transition_style(
    style_name: str,
    stem_name: str,
    window: AudioSegment,
    beat_ms: int,
) -> AudioSegment:
    """Apply the style-specific automation to Song A's transition window."""
    transition_ms = len(window)
    fade_tail_ms = min(beat_ms * 4, transition_ms)

    if style_name == "Style_A":
        if stem_name == "vocals":
            lead = window[: max(0, transition_ms - fade_tail_ms)]
            tail = window[max(0, transition_ms - fade_tail_ms) :].fade_out(fade_tail_ms)
            return combine_segments([lead, tail], window)
        return window

    if style_name == "Style_B":
        return window.fade_out(transition_ms)

    if style_name == "Style_C":
        if stem_name == "vocals":
            return silence_like(window, transition_ms)
        return window

    raise ValueError(f"Unknown style: {style_name}")


def build_song_a_transition_window(
    style_name: str,
    stem_name: str,
    segment: AudioSegment,
    transition_start_ms: int,
    transition_ms: int,
    beat_ms: int,
    chorus_block_ms: tuple[int, int] | None,
) -> AudioSegment:
    """Build Song A's outgoing window for one style."""
    if style_name == "Style_B":
        loop_length_ms = beat_ms * 8
        loop_start_ms = max(0, transition_start_ms - loop_length_ms)
        loop_source = pad_to_length(segment[loop_start_ms:transition_start_ms], loop_length_ms)
        return loop_to_duration(loop_source, transition_ms).fade_out(transition_ms)

    looped_window = build_song_a_loop_window(
        segment=segment,
        transition_start_ms=transition_start_ms,
        transition_ms=transition_ms,
        beat_ms=beat_ms,
        chorus_block_ms=chorus_block_ms,
    )
    return apply_song_a_transition_style(
        style_name=style_name,
        stem_name=stem_name,
        window=looped_window,
        beat_ms=beat_ms,
    )


def build_song_b_transition_window(
    style_name: str,
    window: AudioSegment,
    transition_ms: int,
    song_b_beat_ms: int,
) -> AudioSegment:
    """Build Song B's incoming window for one style."""
    if style_name in {"Style_A", "Style_B", "Style_C"}:
        return window

    raise ValueError(f"Unknown style: {style_name}")


def apply_song_a_cue_pickup(
    style_name: str,
    prefix: AudioSegment,
    segment: AudioSegment,
    chorus_block_ms: tuple[int, int] | None,
    song_a_pickup_ms: int = 0,
) -> AudioSegment:
    """Overlay a one-time cue pickup onto Song A's natural playback before the loop jump."""
    if style_name not in {"Style_A", "Style_B"}:
        return prefix
    if chorus_block_ms is None or song_a_pickup_ms <= 0 or len(prefix) == 0:
        return prefix

    chorus_start_ms, _ = chorus_block_ms
    pickup_start_ms = max(0, chorus_start_ms - song_a_pickup_ms)
    pickup_audio = segment[pickup_start_ms:chorus_start_ms]
    if len(pickup_audio) == 0:
        return prefix

    pickup_audio = standardize_audiosegment(pickup_audio)
    overlay_position = max(0, len(prefix) - len(pickup_audio))
    return standardize_audiosegment(prefix).overlay(pickup_audio, position=overlay_position)
