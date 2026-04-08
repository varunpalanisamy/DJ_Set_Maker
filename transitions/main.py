#!/usr/bin/env python3
"""Pipeline orchestration and CLI for rendering DJ transitions."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from pydub import AudioSegment

from transitions.core.audio_math import (
    build_beat_checkpoint_ms,
    build_master_ramp_checkpoint_ms,
    build_ramp_debug_rows,
    build_virtual_beat_checkpoint_ms,
    calculate_master_transition_duration_ms,
    calculate_preceding_local_bpm,
    calculate_local_bpm,
    count_beats_in_window,
    get_beat_index_for_time,
    get_beat_timestamp,
    get_duration_of_beats,
    get_duration_of_virtual_beats,
    get_effective_bpm_match,
    get_optimal_stretch_ratio,
    get_stretch_mode,
    get_warped_beat_ms,
    ms_to_timestamp,
    scale_warped_timestamp,
    snap_to_nearest_beat,
)
from transitions.core.structural_logic import (
    calculate_pickup_ms,
    calculate_song_a_pickup_ms,
    get_exit_chorus_block,
    get_final_stable_zone,
    get_major_tempo_zones,
    get_optimal_exit_time,
    get_song_b_drop_time,
    get_song_entry_time,
    has_major_tempo_shift,
    load_metadata,
    select_exit_chorus_block_with_reason,
)
from transitions.styles.style_router import (
    apply_song_a_cue_pickup,
    build_song_a_transition_window,
    build_song_b_transition_window,
    build_song_a_loop_window,
    apply_song_a_transition_style,
)
from transitions.tools.audio_utils import (
    STEM_NAMES,
    apply_gain_to_region,
    apply_micro_fades,
    combine_segments,
    detect_low_end_collision,
    overlay_stems,
    overlay_segments_raw,
    overlay_with_headroom,
    pad_to_length,
    protect_from_clipping,
    safe_max_dbfs,
    standardize_audiosegment,
)
from transitions.tools.warper import warp_song_b_stems, warp_transition_segment


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STEMS_DIR = PROJECT_ROOT / "stems"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
STYLE_SPECS = (
    ("Style_A", "Vocal Cut"),
    ("Style_B", "Loop and Fade"),
    ("Style_C", "Instrumental Bed"),
)
DEFAULT_POST_TRANSITION_TAIL_BEATS = 16


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
        stems[stem_name] = standardize_audiosegment(AudioSegment.from_file(stem_path))

    return stems


def apply_song_a_automation(
    style_name: str,
    stem_name: str,
    segment: AudioSegment,
    transition_start_ms: int,
    transition_ms: int,
    beat_ms: int,
    chorus_block_ms: tuple[int, int] | None,
    song_a_pickup_ms: int,
    enable_low_end_management: bool,
) -> AudioSegment:
    """Apply Song A automation for one style."""
    prefix = segment[:transition_start_ms]
    prefix = apply_song_a_cue_pickup(
        style_name=style_name,
        stem_name=stem_name,
        prefix=prefix,
        segment=segment,
        chorus_block_ms=chorus_block_ms,
        song_a_pickup_ms=song_a_pickup_ms,
    )
    processed_window = build_song_a_transition_window(
        style_name=style_name,
        stem_name=stem_name,
        segment=segment,
        transition_start_ms=transition_start_ms,
        transition_ms=transition_ms,
        beat_ms=beat_ms,
        chorus_block_ms=chorus_block_ms,
        enable_low_end_management=enable_low_end_management,
    )
    prefix = standardize_audiosegment(prefix)
    processed_window = standardize_audiosegment(processed_window)
    if len(prefix) == 0:
        return processed_window
    return prefix.append(processed_window, crossfade=min(2, len(prefix), len(processed_window)))


def apply_song_b_automation(
    style_name: str,
    segment: AudioSegment,
    song_b_pickup_ms: int,
    transition_ms: int,
    song_b_beat_ms: int,
    post_transition_tail_ms: int,
) -> AudioSegment:
    """Apply Song B automation for one style."""
    trimmed = segment
    window_ms = song_b_pickup_ms + transition_ms
    required_length = window_ms + post_transition_tail_ms
    trimmed = pad_to_length(trimmed, max(len(trimmed), required_length))
    window = trimmed[:window_ms]
    suffix = trimmed[window_ms : window_ms + post_transition_tail_ms]
    processed_window = build_song_b_transition_window(
        style_name=style_name,
        window=window,
        transition_ms=window_ms,
        song_b_beat_ms=song_b_beat_ms,
    )
    return combine_segments(
        [standardize_audiosegment(processed_window), standardize_audiosegment(suffix)],
        standardize_audiosegment(trimmed),
    )


def render_style(
    style_name: str,
    style_label: str,
    stems_a: dict[str, AudioSegment],
    stems_b_transition: dict[str, AudioSegment],
    stems_b_full: dict[str, AudioSegment],
    transition_start_ms: int,
    song_b_pickup_ms: int,
    transition_ms: int,
    song_b_target_ms: int,
    beat_ms: int,
    song_b_beat_ms: int,
    post_transition_tail_ms: int,
    chorus_block_ms: tuple[int, int] | None,
    song_a_pickup_ms: int,
    output_path: Path,
    song_a_source_transition_ms: int | None = None,
    song_a_ramp_bpm: tuple[float, float, int] | None = None,
    gradual_temp_dir: Path | None = None,
    song_a_source_checkpoint_ms: list[int] | None = None,
    song_b_target_checkpoint_ms: list[int] | None = None,
) -> Path:
    """Render one transition style and export it."""
    def build_processed_a(enable_low_end_management: bool) -> dict[str, AudioSegment]:
        if song_a_ramp_bpm is not None:
            if gradual_temp_dir is None or song_a_source_transition_ms is None:
                raise ValueError("Gradual Song A rendering requires a temp dir and source duration.")
            processed: dict[str, AudioSegment] = {}
            for stem_name, stem_audio in stems_a.items():
                prefix = stem_audio[:transition_start_ms]
                prefix = apply_song_a_cue_pickup(
                    style_name=style_name,
                    stem_name=stem_name,
                    prefix=prefix,
                    segment=stem_audio,
                    chorus_block_ms=chorus_block_ms,
                    song_a_pickup_ms=song_a_pickup_ms,
                )
                source_window = build_song_a_loop_window(
                    segment=stem_audio,
                    transition_start_ms=transition_start_ms,
                    transition_ms=song_a_source_transition_ms,
                    beat_ms=beat_ms,
                    chorus_block_ms=chorus_block_ms,
                )
                warped_window = warp_transition_segment(
                    segment=source_window,
                    start_bpm=song_a_ramp_bpm[0],
                    end_bpm=song_a_ramp_bpm[1],
                    target_duration_ms=song_a_ramp_bpm[2],
                    temp_dir=gradual_temp_dir / "song_a",
                    stem_name=f"{style_name}_{stem_name}",
                    source_checkpoint_ms=song_a_source_checkpoint_ms,
                    target_checkpoint_ms=song_b_target_checkpoint_ms,
                )
                warped_window = pad_to_length(warped_window, transition_ms)
                styled_window = apply_song_a_transition_style(
                    style_name=style_name,
                    stem_name=stem_name,
                    window=warped_window[:transition_ms],
                    beat_ms=beat_ms,
                    enable_low_end_management=enable_low_end_management,
                )
                processed[stem_name] = combine_segments([prefix, styled_window], stem_audio)
            return processed

        return {
            stem_name: apply_song_a_automation(
                style_name=style_name,
                stem_name=stem_name,
                segment=stem_audio,
                transition_start_ms=transition_start_ms,
                transition_ms=transition_ms,
                beat_ms=beat_ms,
                chorus_block_ms=chorus_block_ms,
                song_a_pickup_ms=song_a_pickup_ms,
                enable_low_end_management=enable_low_end_management,
            )
            for stem_name, stem_audio in stems_a.items()
        }

    def stabilize_transition_peak_levels(
        processed_song_a: dict[str, AudioSegment],
        processed_song_b: dict[str, AudioSegment],
    ) -> tuple[dict[str, AudioSegment], dict[str, AudioSegment]]:
        peak_ceiling = -0.1
        max_iterations = 10
        candidate_order = (
            ("song_b", "bass"),
            ("song_b", "drums"),
            ("song_a", "bass"),
            ("song_a", "drums"),
            ("song_b", "other"),
            ("song_a", "other"),
            ("song_b", "vocals"),
            ("song_a", "vocals"),
        )

        for _ in range(max_iterations):
            overlap_components: list[AudioSegment] = []
            component_peaks: list[tuple[str, str, float]] = []

            for track_name, stem_name in candidate_order:
                if track_name == "song_a":
                    component = pad_to_length(
                        processed_song_a[stem_name][overlay_start_ms : overlay_start_ms + song_b_window_ms],
                        song_b_window_ms,
                    )
                else:
                    component = pad_to_length(processed_song_b[stem_name][:song_b_window_ms], song_b_window_ms)
                overlap_components.append(component)
                component_peaks.append((track_name, stem_name, safe_max_dbfs(component)))

            combined_overlap = overlay_segments_raw(overlap_components)
            if safe_max_dbfs(combined_overlap) <= peak_ceiling:
                break

            offending_track, offending_stem, offending_peak = max(component_peaks, key=lambda item: item[2])
            if offending_peak == float("-inf"):
                break

            reduction_db = min(3.5, max(1.0, safe_max_dbfs(combined_overlap) - peak_ceiling + 0.5))
            if offending_track == "song_a":
                processed_song_a[offending_stem] = apply_gain_to_region(
                    processed_song_a[offending_stem],
                    overlay_start_ms,
                    overlay_start_ms + song_b_window_ms,
                    -reduction_db,
                )
            else:
                processed_song_b[offending_stem] = apply_gain_to_region(
                    processed_song_b[offending_stem],
                    0,
                    song_b_window_ms,
                    -reduction_db,
                )
            print(
                f"[Mix] Peak protection reduced {offending_track} {offending_stem} "
                f"by {reduction_db:.1f} dB in the transition window."
            )

        return processed_song_a, processed_song_b

    processed_b = {
        stem_name: apply_song_b_automation(
            style_name=style_name,
            segment=stem_audio,
            song_b_pickup_ms=song_b_pickup_ms,
            transition_ms=transition_ms,
            song_b_beat_ms=song_b_beat_ms,
            post_transition_tail_ms=post_transition_tail_ms,
        )
        for stem_name, stem_audio in stems_b_transition.items()
    }

    song_b_window_ms = song_b_pickup_ms + transition_ms
    overlay_start_ms = max(0, transition_start_ms - song_b_pickup_ms)
    processed_a = build_processed_a(enable_low_end_management=False)

    low_end_collision = detect_low_end_collision(
        pad_to_length(processed_a["bass"][overlay_start_ms : overlay_start_ms + song_b_window_ms], song_b_window_ms)
        .overlay(
            pad_to_length(processed_a["drums"][overlay_start_ms : overlay_start_ms + song_b_window_ms], song_b_window_ms)
        ),
        pad_to_length(processed_b["bass"][:song_b_window_ms], song_b_window_ms).overlay(
            pad_to_length(processed_b["drums"][:song_b_window_ms], song_b_window_ms)
        ),
    )
    if low_end_collision:
        print("[Mix] Low-end collision detected. Applying bass/drum ducking and filtering.")
        processed_a = build_processed_a(enable_low_end_management=True)

    processed_a, processed_b = stabilize_transition_peak_levels(processed_a, processed_b)

    mix_a = overlay_stems(processed_a)
    mix_b = overlay_stems(processed_b)
    mix_a_with_transition = pad_to_length(mix_a, transition_start_ms + transition_ms)
    if low_end_collision:
        overlap_mix = overlay_with_headroom(
            mix_a_with_transition,
            mix_b[:song_b_window_ms],
            position=overlay_start_ms,
        )
    else:
        overlap_mix = mix_a_with_transition.overlay(
            mix_b[:song_b_window_ms],
            position=overlay_start_ms,
        )

    song_b_body_stems = {
        stem_name: stem_audio[song_b_target_ms:]
        for stem_name, stem_audio in stems_b_full.items()
    }
    song_b_body_mix = apply_micro_fades(overlay_stems(song_b_body_stems))
    overlap_mix = standardize_audiosegment(overlap_mix)
    final_mix = overlap_mix.append(
        standardize_audiosegment(song_b_body_mix),
        crossfade=min(2, len(overlap_mix), len(song_b_body_mix)),
    )
    final_mix = protect_from_clipping(final_mix)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_mix.export(output_path, format="mp3", bitrate="320k")
    return output_path


def render_all_styles(
    song_a_id: str,
    song_b_id: str,
    pair_output_dir: Path,
    post_transition_tail_beats: int = DEFAULT_POST_TRANSITION_TAIL_BEATS,
) -> list[Path]:
    """Render all transition styles for one adjacent pair of tracks."""
    pair_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Render] Loading metadata for {song_a_id} -> {song_b_id}")
    metadata_a = load_metadata(song_a_id)
    metadata_b = load_metadata(song_b_id)
    final_zone_a = get_final_stable_zone(metadata_a)

    bpm_a = float(metadata_a["bpm"])
    bpm_b = float(metadata_b["bpm"])

    entry_time_sec = get_song_entry_time(metadata_b)
    drop_time_sec = get_song_b_drop_time(metadata_b, entry_time=entry_time_sec)
    local_entry_bpm_b = calculate_local_bpm(metadata_b, entry_time_sec, drop_time_sec)
    song_b_pickup_ms = calculate_pickup_ms(metadata_b, entry_time_sec)
    stretch_ratio = get_optimal_stretch_ratio(bpm_a, local_entry_bpm_b)
    stretch_mode = get_stretch_mode(bpm_a, local_entry_bpm_b)

    original_song_b_entry_ms = int(round(entry_time_sec * 1000.0))
    original_song_b_entry_ms = snap_to_nearest_beat(original_song_b_entry_ms, metadata_b)
    raw_song_a_exit_ms = int(round(get_optimal_exit_time(metadata_a) * 1000.0))
    exit_beat_index = get_beat_index_for_time(metadata_a, raw_song_a_exit_ms / 1000.0)
    entry_beat_index = get_beat_index_for_time(metadata_b, original_song_b_entry_ms / 1000.0)
    exit_chorus_block, exit_chorus_reason = select_exit_chorus_block_with_reason(metadata_a)
    local_exit_bpm_a = calculate_preceding_local_bpm(metadata_a, raw_song_a_exit_ms)
    effective_mode, effective_exit_bpm_a, song_a_beat_factor = get_effective_bpm_match(
        local_exit_bpm_a, local_entry_bpm_b
    )

    beat_ms = int(round(60000.0 / effective_exit_bpm_a))
    bar_ms = beat_ms * 4
    song_b_drop_ms = int(round(drop_time_sec * 1000.0))
    structural_transition_source_ms = song_b_drop_ms - original_song_b_entry_ms
    if structural_transition_source_ms <= 0:
        raise ValueError("Dynamic transition duration must be positive.")
    transition_beats = count_beats_in_window(metadata_b, entry_time_sec, drop_time_sec)
    if transition_beats <= 0:
        raise ValueError("Could not determine transition beat count for the shared ramp.")
    target_duration_a_ms = int(
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
    source_duration_b_ms = int(round(get_duration_of_beats(metadata_b, entry_beat_index, transition_beats) * 1000.0))
    if target_duration_a_ms <= 0 or source_duration_b_ms <= 0:
        raise ValueError("Could not determine beat-matched transition durations.")
    master_transition_ms = calculate_master_transition_duration_ms(
        transition_beats=transition_beats,
        start_bpm=effective_exit_bpm_a,
        end_bpm=local_entry_bpm_b,
    )
    song_a_source_transition_ms = max(1, target_duration_a_ms)
    song_a_checkpoint_ms = build_virtual_beat_checkpoint_ms(
        metadata_a,
        exit_beat_index,
        transition_beats,
        song_a_beat_factor,
    )
    song_b_checkpoint_ms = build_beat_checkpoint_ms(metadata_b, entry_beat_index, transition_beats)
    master_ramp_checkpoint_ms = build_master_ramp_checkpoint_ms(
        transition_beats=transition_beats,
        start_bpm=effective_exit_bpm_a,
        end_bpm=local_entry_bpm_b,
    )
    post_transition_tail_ms = beat_ms * max(0, post_transition_tail_beats)
    transition_start_ms = int(round(get_beat_timestamp(metadata_a, exit_beat_index) * 1000.0))
    stretch_ratio = source_duration_b_ms / target_duration_a_ms
    stretch_mode = effective_mode
    ramp_start_bpm = effective_exit_bpm_a
    ramp_end_bpm = local_entry_bpm_b
    ramp_start_ratio = effective_exit_bpm_a / local_entry_bpm_b if local_entry_bpm_b > 0 else 1.0
    song_b_beat_ms = get_warped_beat_ms(local_entry_bpm_b, stretch_ratio)
    song_b_target_ms = song_b_drop_ms
    transition_ms = target_duration_a_ms
    chorus_block_ms = None
    song_a_pickup_ms = 0
    if exit_chorus_block is not None:
        chorus_block_ms = (
            int(round(float(exit_chorus_block["aligned_start_time"]) * 1000.0)),
            int(round(float(exit_chorus_block["aligned_end_time"]) * 1000.0)),
        )
        song_a_pickup_ms = calculate_song_a_pickup_ms(
            metadata_a,
            float(exit_chorus_block["aligned_start_time"]),
        )

    if has_major_tempo_shift(metadata_a):
        print("THERE IS A BEAT SWITCH IN THIS SONG.")
        for index, zone in enumerate(get_major_tempo_zones(metadata_a), start=1):
            print(
                f"[Logic] Major Zone {index}: "
                f"{float(zone['start_time']):.2f}s -> {float(zone['end_time']):.2f}s "
                f"at {float(zone['bpm']):.2f} BPM"
            )
        print("[Logic] Beat-switch detected. Locking exit point to the final high-energy zone.")
        print(
            f"[Ramp] Beat-switch detected in Song A. Anchoring ramp start to local exit BPM: "
            f"{effective_exit_bpm_a:.2f}."
        )
    if exit_chorus_block is not None:
        print(
            f"PICKED TRANSITION AT THIS CHORUS: "
            f"{ms_to_timestamp(int(round(float(exit_chorus_block['aligned_start_time']) * 1000.0)))}"
            f" -> "
            f"{ms_to_timestamp(int(round(float(exit_chorus_block['aligned_end_time']) * 1000.0)))} | "
            f"{exit_chorus_reason}"
        )
    print(f"[Render] Song A BPM: {bpm_a:.2f}")
    print(f"[Render] Song A local exit BPM: {local_exit_bpm_a:.2f}")
    print(f"[Render] Song A effective exit BPM: {effective_exit_bpm_a:.2f} ({effective_mode})")
    print(f"[Render] Song B BPM: {bpm_b:.2f}")
    print(f"[Render] Song B local entry BPM: {local_entry_bpm_b:.2f}")
    print(f"[Render] BPM match mode: {stretch_mode}")
    print(f"[Render] Stretch ratio: {stretch_ratio:.6f}")
    print(f"[Render] Gradual BPM ramp: {ramp_start_bpm:.2f} -> {ramp_end_bpm:.2f}")
    print(f"[Render] 1 beat = {beat_ms} ms | 1 bar = {bar_ms} ms")
    print(f"[Render] Song A exit = {ms_to_timestamp(raw_song_a_exit_ms)}")
    print(f"[Render] Beat-aligned start = {ms_to_timestamp(transition_start_ms)}")
    print(f"[Render] Song B entry (beat-aligned) = {ms_to_timestamp(original_song_b_entry_ms)}")
    print(f"[Render] Song B drop point = {ms_to_timestamp(song_b_drop_ms)}")
    print(f"[Render] Song B pickup preroll = {song_b_pickup_ms} ms")
    print(f"[Render] Shared transition beats = {transition_beats}")
    print(f"[Render] Shared gradual target duration = {master_transition_ms} ms")
    print(f"[Render] Dynamic transition duration = {transition_ms} ms")
    print(f"[Render] Song B tail after transition = {post_transition_tail_beats} beats")
    for row in build_ramp_debug_rows(master_ramp_checkpoint_ms, effective_exit_bpm_a, local_entry_bpm_b):
        print(row)
    if chorus_block_ms is not None:
        print(
            f"[Render] Song A loop chorus = {ms_to_timestamp(chorus_block_ms[0])} -> {ms_to_timestamp(chorus_block_ms[1])}"
        )
        print(f"[Render] Song A cue pickup = {song_a_pickup_ms} ms")

    stems_a = load_stems(song_a_id)
    stems_b_full = load_stems(song_b_id)
    render_modes = (
        {
            "name": "constant",
            "output_dir": pair_output_dir,
            "stretch_ratio": stretch_ratio,
            "song_b_beat_ms": song_b_beat_ms,
            "song_b_pickup_ms": scale_warped_timestamp(song_b_pickup_ms, stretch_ratio),
            "tempo_map": None,
            "song_a_ramp_bpm": None,
            "transition_ms": transition_ms,
        },
        {
            "name": "gradual_bpm",
            "output_dir": pair_output_dir / "gradual_bpm",
            "stretch_ratio": ramp_start_ratio,
            "song_b_beat_ms": get_warped_beat_ms(local_entry_bpm_b, ramp_start_ratio),
            "song_b_pickup_ms": scale_warped_timestamp(song_b_pickup_ms, ramp_start_ratio),
            "tempo_map": (effective_exit_bpm_a, local_entry_bpm_b, master_transition_ms),
            "song_a_ramp_bpm": (effective_exit_bpm_a, local_entry_bpm_b, master_transition_ms),
            "transition_ms": master_transition_ms,
        },
    )

    rendered_paths: list[Path] = []
    for render_mode in render_modes:
        with tempfile.TemporaryDirectory(
            prefix=f"{song_a_id}_to_{song_b_id}_{render_mode['name']}_",
            dir=PROJECT_ROOT,
        ) as temp_dir_str:
            stems_b_transition = warp_song_b_stems(
                song_b_id,
                render_mode["stretch_ratio"],
                Path(temp_dir_str),
                transition_source_duration_ms=source_duration_b_ms,
                original_song_b_entry_ms=original_song_b_entry_ms,
                pickup_ms=song_b_pickup_ms,
                target_pickup_ms=render_mode["song_b_pickup_ms"],
                tempo_map=render_mode["tempo_map"],
                source_checkpoint_ms=song_b_checkpoint_ms if render_mode["tempo_map"] is not None else None,
                target_checkpoint_ms=master_ramp_checkpoint_ms if render_mode["tempo_map"] is not None else None,
            )
            mode_transition_ms = render_mode["transition_ms"]
            for style_name, style_label in STYLE_SPECS:
                output_path = render_mode["output_dir"] / f"{style_name}.mp3"
                render_style(
                    style_name=style_name,
                    style_label=style_label,
                    stems_a=stems_a,
                    stems_b_transition=stems_b_transition,
                    stems_b_full=stems_b_full,
                    transition_start_ms=transition_start_ms,
                    song_b_pickup_ms=render_mode["song_b_pickup_ms"],
                    transition_ms=mode_transition_ms,
                    song_b_target_ms=song_b_target_ms,
                    beat_ms=beat_ms,
                    song_b_beat_ms=render_mode["song_b_beat_ms"],
                    post_transition_tail_ms=post_transition_tail_ms,
                    chorus_block_ms=chorus_block_ms,
                    song_a_pickup_ms=song_a_pickup_ms,
                    output_path=output_path,
                    song_a_source_transition_ms=song_a_source_transition_ms,
                    song_a_ramp_bpm=render_mode["song_a_ramp_bpm"],
                    gradual_temp_dir=Path(temp_dir_str),
                    song_a_source_checkpoint_ms=song_a_checkpoint_ms if render_mode["tempo_map"] is not None else None,
                    song_b_target_checkpoint_ms=master_ramp_checkpoint_ms if render_mode["tempo_map"] is not None else None,
                )
                rendered_paths.append(output_path)

    return rendered_paths


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for direct pair rendering."""
    parser = argparse.ArgumentParser(description="Render all transition styles for a single song pair.")
    parser.add_argument("song_a_id", help="Track ID for Song A (outgoing track).")
    parser.add_argument("song_b_id", help="Track ID for Song B (incoming track).")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory. Defaults to outputs/<song_a_id>_to_<song_b_id>/",
    )
    parser.add_argument(
        "--tail-beats",
        type=int,
        default=DEFAULT_POST_TRANSITION_TAIL_BEATS,
        help="Number of Song B beats to keep after the transition window.",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint for rendering one explicit song pair."""
    args = parse_args()
    output_dir = args.output_dir or (OUTPUTS_DIR / f"{args.song_a_id}_to_{args.song_b_id}")
    render_all_styles(
        song_a_id=args.song_a_id,
        song_b_id=args.song_b_id,
        pair_output_dir=output_dir,
        post_transition_tail_beats=args.tail_beats,
    )


if __name__ == "__main__":
    main()
