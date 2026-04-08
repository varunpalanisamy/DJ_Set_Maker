#!/usr/bin/env python3
"""Compatibility wrapper for the transitions package."""

from transitions.main import *  # noqa: F401,F403
from transitions.main import main


def order_setlist_by_bpm(tracks: list[dict]) -> list[dict]:
    """Order tracks from slowest to fastest BPM."""
    return sorted(tracks, key=lambda track: (float(track["bpm"]), track["track_id"]))


if __name__ == "__main__":
    main()
