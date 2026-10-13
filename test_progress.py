#!/usr/bin/env python3
"""Test progress callback in sync engine."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from flamquency.sync_engine import FlamQuencySync
from flamquency.config import DEFAULT_CONFIG
from flamquency.cloud import LocalBackend
import copy

config = copy.deepcopy(DEFAULT_CONFIG)
config['use_ignore_file'] = False

with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir) / '.flamquency_isolated'
    backend = LocalBackend(base_path=base / 'sync')
    sync = FlamQuencySync(config=config, backend=backend, base_dir=base)
    
    # Create many files
    t = Path(tmpdir)
    for i in range(50):
        (t / f'file_{i}.txt').write_text(f'content {i}')
    
    # Test progress callback
    events = []
    def progress_cb(p):
        events.append((p.done, p.total, p.current))
    
    result = sync.sync(source=t, progress=progress_cb)
    print(f'Files synced: {result.files_synced}')
    print(f'Progress events: {len(events)}')
    print(f'First event: {events[0]}')
    print(f'Last event: {events[-1]}')
    print('Progress callback works!')