#!/usr/bin/env python3
"""Test TUI imports."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from flamquency.textual_tui import SyncScreen
print('TUI imports OK')