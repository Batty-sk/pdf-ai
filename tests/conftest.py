"""Keep Qt offscreen and give each test a private data directory."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
