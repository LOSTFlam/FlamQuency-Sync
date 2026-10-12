#!/usr/bin/env python3
"""Test suite for FlamQuency-Sync."""
import sys
import os
import tempfile
import shutil
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flamquency.sync_engine import FlamQuencySync, SyncResult, LocalBackend
from flamquency.config import load_config, save_config
from flamquency.version_store import VersionStore, BlobStore
from flamquency.cloud import get_backend


def _isolated_sync(tmpdir):
    """Create a FlamQuencySync with isolated storage in a temp dir."""
    config = load_config()
    base = Path(tmpdir) / ".flamquency_isolated"
    backend = LocalBackend(base_path=base / "sync")
    sync = FlamQuencySync(config=config, backend=backend)
    # Override paths to temp
    sync.base_dir = base
    sync.snapshot_dir = base / "snapshots"
    sync.snapshot_dir.mkdir(parents=True, exist_ok=True)
    sync.version_store = VersionStore(base / "versions")
    sync.version_dir = base / "versions" / "files"
    sync.version_dir.mkdir(parents=True, exist_ok=True)
    return sync


def test_config_load():
    config = load_config()
    assert "cloud_backend" in config
    assert "exclude_patterns" in config
    print("✓ Config loading works")


def test_scan_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        (t / "config.txt").write_text("test")
        (t / "cache").mkdir()
        (t / "cache" / "temp.tmp").write_text("cache")
        
        files = sync.scan_directory(t)
        assert any("config.txt" in str(f) for f in files)
        assert not any("temp.tmp" in str(f) for f in files)
    print("✓ Directory scanning with exclusions works")


def test_hash_computation():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("hello world")
        h1 = sync.compute_hash(test_file)
        h2 = sync.compute_hash(test_file)
        assert h1 == h2
        assert len(h1) == 64
    print("✓ Hash computation works")


def test_blob_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        bs = BlobStore(Path(tmpdir))
        h1 = bs.store("hello world")
        assert len(h1) == 64
        h2 = bs.store("hello world")
        assert h1 == h2  # Dedup
        data = bs.retrieve(h1)
        assert data == b"hello world"
        
        test_file = Path(tmpdir) / "test_file.txt"
        test_file.write_text("file content here")
        h3 = bs.store_file(test_file)
        assert bs.has(h3)
        
        dest = Path(tmpdir) / "restored.txt"
        assert bs.restore_to(h3, dest)
        assert dest.read_text() == "file content here"
    print("✓ Blob store works (store, dedup, retrieve, restore)")


def test_version_store_record_and_restore():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VersionStore(Path(tmpdir))
        h1, new1 = vs.record_version("test/file.txt", data="version 1 content")
        assert new1
        h2, new2 = vs.record_version("test/file.txt", data="version 2 content")
        assert new2
        h2b, new2b = vs.record_version("test/file.txt", data="version 2 content")
        assert not new2b  # Identical = no new version
        
        history = vs.get_history("test/file.txt")
        assert len(history) == 2
        
        dest = Path(tmpdir) / "restored_v1.txt"
        success, msg = vs.restore_version("test/file.txt", 0, dest_path=dest)
        assert success
        assert dest.read_text() == "version 1 content"
        
        dest2 = Path(tmpdir) / "restored_v2.txt"
        vs.restore_version("test/file.txt", 1, dest_path=dest2)
        assert dest2.read_text() == "version 2 content"
    print("✓ Version store record & restore works")


def test_version_store_diff():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VersionStore(Path(tmpdir))
        vs.record_version("config.txt", data="line1\nline2\nline3\n")
        vs.record_version("config.txt", data="line1\nmodified\nline3\n")
        diff = vs.diff_versions("config.txt", 0, 1)
        assert diff is not None
        assert "modified" in diff
    print("✓ Version diff works")


def test_snapshot_creation():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        # Create some test data
        t = Path(tmpdir)
        (t / "test.txt").write_text("hello")
        (t / "sub").mkdir()
        (t / "sub" / "nested.txt").write_text("nested")
        
        snap, meta = sync.create_snapshot(source_path=t)
        assert snap.exists()
        assert meta["file_count"] >= 2
        assert "manifest" in meta
    print("✓ Snapshot creation works")


def test_sync_with_versions():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        
        (t / "test.txt").write_text("content v1")
        (t / "sub").mkdir()
        (t / "sub" / "test2.txt").write_text("another file")
        
        result = sync.sync(source=t)
        assert result.files_synced >= 2
        
        # Modify and re-sync
        (t / "test.txt").write_text("content v2")
        sync.sync(source=t)
        
        # Check version history
        history = sync.version_store.get_history("test.txt")
        assert len(history) >= 2, f"Expected >=2 versions, got {len(history)}"
        
        # Restore old version
        dest = t / "restored.txt"
        success, msg = sync.version_store.restore_version("test.txt", 0, dest_path=dest)
        assert success
        assert dest.read_text() == "content v1"
    print("✓ Sync with real version storage works")


def test_rollback_snapshot():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        (t / "test.txt").write_text("snapshot data")
        
        snap, meta = sync.create_snapshot(source_path=t)
        success, msg = sync.rollback_to_snapshot(snap.name, target_path=t)
        assert success
        assert (t / "test.txt").read_text() == "snapshot data"
    print("✓ Snapshot rollback works")


def test_rollback_file_real():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        
        test_file = t / "test.txt"
        test_file.write_text("original")
        
        # Sync v1
        sync.sync(source=t)
        
        # Modify and sync v2
        test_file.write_text("modified")
        sync.sync(source=t)
        
        # Check versions
        history = sync.version_store.get_history("test.txt")
        assert len(history) == 2, f"Expected 2, got {len(history)}"
        
        # Restore v0 (original)
        success, info = sync.rollback_file(str(test_file), version_index=0)
        assert success, f"rollback failed: {info}"
        assert test_file.read_text() == "original", f"Got: {test_file.read_text()}"
    print("✓ Real per-file rollback works")


def test_version_listing():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VersionStore(Path(tmpdir))
        vs.record_version("test.txt", data="v1")
        vs.record_version("test.txt", data="v2")
        vs.record_version("test.txt", data="v3")
        
        versions = vs.list_versions("test.txt")
        assert len(versions) == 3
        assert versions[0]["index"] == 0
        assert versions[2]["index"] == 2
    print("✓ Version listing works")


def test_gc_and_prune():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VersionStore(Path(tmpdir))
        for i in range(10):
            vs.record_version("test.txt", data=f"version {i}")
        assert len(vs.get_history("test.txt")) == 10
        
        pruned = vs.prune(keep_last_n=5)
        assert pruned == 5
        assert len(vs.get_history("test.txt")) == 5
        
        removed = vs.gc()
        assert removed >= 0
    print("✓ GC and prune work")


def test_backend_factory():
    backend = get_backend("local")
    assert isinstance(backend, LocalBackend)
    assert backend.authenticate()
    print("✓ Backend factory works")


def main():
    print("🔥 Running FlamQuency-Sync tests...\n")
    
    tests = [
        test_config_load,
        test_scan_directory,
        test_hash_computation,
        test_blob_store,
        test_version_store_record_and_restore,
        test_version_store_diff,
        test_snapshot_creation,
        test_sync_with_versions,
        test_rollback_snapshot,
        test_rollback_file_real,
        test_version_listing,
        test_gc_and_prune,
        test_backend_factory,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Tests: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print(f"{'='*50}")
    
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
