"""Hermetic audio: the suite never spawns platform players (TSURV_AUDIO=0)."""

from __future__ import annotations

import os

os.environ.setdefault("TSURV_AUDIO", "0")
