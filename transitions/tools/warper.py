"""Shell wrappers and time-warping helpers for ffmpeg and Rubber Band."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from pydub import AudioSegment

from transitions.tools.audio_utils import (
    MASTER_TRANSITION_SAMPLE_RATE,
    STEM_NAMES,
    apply_micro_fades,
    silence_like,
    standardize_audiosegment,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STEMS_DIR = PROJECT_ROOT / "stems"


def offset_checkpoint_ms(checkpoints: list[int] | None, offset_ms: int) -> list[int] | None:
    """Shift checkpoint times forward by a pickup offset."""
    if checkpoints is None:
        return None
    if offset_ms <= 0:
        return list(checkpoints)
    return [max(0, int(checkpoint) + offset_ms) for checkpoint in checkpoints]


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


def generate_tempo_map(
    source_duration_ms: int,
    target_duration_ms: int,
    start_bpm: float,
    end_bpm: float,
    sample_rate: int,
    output_path: Path,
    num_points: int = 32,
    source_checkpoint_ms: list[int] | None = None,
    target_checkpoint_ms: list[int] | None = None,
) -> Path:
    """Create a deterministic Rubber Band tempo map from a shared master BPM ramp."""
    if source_duration_ms <= 0:
        raise ValueError("Source duration must be positive.")
    if target_duration_ms <= 0:
        raise ValueError("Target duration must be positive.")
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive.")
    if start_bpm <= 0 or end_bpm <= 0:
        raise ValueError("Tempo values must be positive.")

    source_frames = max(1, int(round(source_duration_ms * sample_rate / 1000.0)))
    target_frames = max(1, int(round(target_duration_ms * sample_rate / 1000.0)))

    if source_checkpoint_ms is not None or target_checkpoint_ms is not None:
        if not source_checkpoint_ms or not target_checkpoint_ms:
            raise ValueError("Both source and target checkpoints are required together.")
        if len(source_checkpoint_ms) != len(target_checkpoint_ms):
            raise ValueError("Source and target checkpoint counts must match.")

        map_lines: list[str] = []
        previous_target_frame = -1
        for index, (source_ms, target_ms) in enumerate(zip(source_checkpoint_ms, target_checkpoint_ms)):
            source_frame = min(source_frames, max(0, int(round(source_ms * sample_rate / 1000.0))))
            target_frame = min(target_frames, max(0, int(round(target_ms * sample_rate / 1000.0))))
            if index == len(source_checkpoint_ms) - 1:
                source_frame = source_frames
                target_frame = target_frames
            elif index > 0:
                target_frame = max(target_frame, previous_target_frame + 1)
            previous_target_frame = target_frame
            map_lines.append(f"{source_frame} {target_frame}")

        output_path.write_text("\n".join(map_lines) + "\n", encoding="utf-8")
        return output_path

    def cumulative_time(progress: float) -> float:
        if abs(end_bpm - start_bpm) < 1e-9:
            return progress / start_bpm
        bpm_at_progress = start_bpm + ((end_bpm - start_bpm) * progress)
        return math.log(bpm_at_progress / start_bpm) / (end_bpm - start_bpm)

    total_time = cumulative_time(1.0)
    map_lines: list[str] = []
    previous_target_frame = -1
    for point_index in range(num_points + 1):
        progress = point_index / num_points
        source_frame = int(round(source_frames * progress))
        if point_index == num_points:
            target_frame = target_frames
        else:
            target_progress = cumulative_time(progress) / total_time if total_time > 0 else progress
            target_frame = int(round(target_frames * target_progress))
            target_frame = max(target_frame, previous_target_frame + 1 if point_index > 0 else 0)
            target_frame = min(target_frame, target_frames)
        previous_target_frame = target_frame
        map_lines.append(f"{source_frame} {target_frame}")

    output_path.write_text("\n".join(map_lines) + "\n", encoding="utf-8")
    return output_path


def warp_transition_segment(
    segment: AudioSegment,
    start_bpm: float,
    end_bpm: float,
    target_duration_ms: int,
    temp_dir: Path,
    stem_name: str,
    source_checkpoint_ms: list[int] | None = None,
    target_checkpoint_ms: list[int] | None = None,
) -> AudioSegment:
    """Warp an in-memory transition segment to follow a shared tempo ramp."""
    ensure_tool_available("rubberband")
    temp_dir.mkdir(parents=True, exist_ok=True)

    source_duration_ms = len(segment)
    if source_duration_ms <= 0:
        return silence_like(segment, 0)
    if target_duration_ms <= 0:
        raise ValueError("Target duration must be positive for transition warping.")
    if start_bpm <= 0 or end_bpm <= 0:
        raise ValueError("BPM values must be positive for transition warping.")

    source_path = temp_dir / f"{stem_name}_source.wav"
    warped_path = temp_dir / f"{stem_name}_warped.wav"
    segment = standardize_audiosegment(segment)
    segment.export(source_path, format="wav")

    rubberband_command = ["rubberband"]
    tempo_map_path = generate_tempo_map(
        source_duration_ms=source_duration_ms,
        target_duration_ms=target_duration_ms,
        start_bpm=start_bpm,
        end_bpm=end_bpm,
        sample_rate=MASTER_TRANSITION_SAMPLE_RATE,
        output_path=temp_dir / f"{stem_name}_tempo_map.txt",
        source_checkpoint_ms=source_checkpoint_ms,
        target_checkpoint_ms=target_checkpoint_ms,
    )
    rubberband_command.extend(
        [
            "--duration",
            f"{target_duration_ms / 1000.0:.6f}",
            "--timemap",
            str(tempo_map_path),
            str(source_path),
            str(warped_path),
        ]
    )
    run_command(rubberband_command)
    warped_segment = standardize_audiosegment(AudioSegment.from_file(warped_path))
    return apply_micro_fades(warped_segment)


def _load_stems_from_dir(stem_dir: Path) -> dict[str, AudioSegment]:
    """Load stems from a concrete directory."""
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


def warp_song_b_stems(
    track_id: str,
    stretch_ratio: float,
    temp_dir: Path,
    transition_source_duration_ms: int,
    original_song_b_entry_ms: int,
    pickup_ms: int = 0,
    target_pickup_ms: int = 0,
    tempo_map: tuple[float, float, int] | None = None,
    source_checkpoint_ms: list[int] | None = None,
    target_checkpoint_ms: list[int] | None = None,
) -> dict[str, AudioSegment]:
    """Warp only Song B's transition section to Song A's BPM using ffmpeg + Rubber Band."""
    ensure_tool_available("ffmpeg")
    ensure_tool_available("rubberband")

    source_dir = STEMS_DIR / track_id
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Stem directory not found: {source_dir}")

    converted_dir = temp_dir / "converted"
    warped_dir = temp_dir / "warped"
    converted_dir.mkdir(parents=True, exist_ok=True)
    warped_dir.mkdir(parents=True, exist_ok=True)
    source_seek_ms = max(0, original_song_b_entry_ms - pickup_ms)
    source_segment_ms = transition_source_duration_ms + pickup_ms

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
        segment_path = converted_dir / f"{stem_name}_transition.wav"

        run_command(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-ar",
                str(MASTER_TRANSITION_SAMPLE_RATE),
                str(converted_path),
            ]
        )

        run_command(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{source_seek_ms / 1000.0:.6f}",
                "-accurate_seek",
                "-i",
                str(converted_path),
                "-ar",
                str(MASTER_TRANSITION_SAMPLE_RATE),
                "-t",
                f"{source_segment_ms / 1000.0:.6f}",
                str(segment_path),
            ]
        )

        rubberband_command = ["rubberband"]
        if tempo_map is not None:
            target_segment_ms = tempo_map[2] + target_pickup_ms
            tempo_map_path = generate_tempo_map(
                source_duration_ms=source_segment_ms,
                target_duration_ms=target_segment_ms,
                start_bpm=tempo_map[0],
                end_bpm=tempo_map[1],
                sample_rate=MASTER_TRANSITION_SAMPLE_RATE,
                output_path=converted_dir / f"{stem_name}_tempo_map.txt",
                source_checkpoint_ms=offset_checkpoint_ms(source_checkpoint_ms, pickup_ms),
                target_checkpoint_ms=offset_checkpoint_ms(target_checkpoint_ms, target_pickup_ms),
            )
            rubberband_command.extend(
                [
                    "--duration",
                    f"{target_segment_ms / 1000.0:.6f}",
                    "--timemap",
                    str(tempo_map_path),
                ]
            )
        else:
            rubberband_command.extend(["--tempo", f"{stretch_ratio:.8f}"])

        rubberband_command.extend([str(segment_path), str(warped_path)])
        run_command(rubberband_command)

    warped_stems = _load_stems_from_dir(warped_dir)
    return {stem_name: apply_micro_fades(stem_audio) for stem_name, stem_audio in warped_stems.items()}
