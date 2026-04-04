#!/usr/bin/env python3
"""Compatibility wrapper for the transitions package."""

from transitions.main import *  # noqa: F401,F403
from transitions.main import main


if __name__ == "__main__":
    main()
