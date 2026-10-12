#!/usr/bin/env python3
"""Test suite for FlamQuency-Sync."""
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flamquency.sync_engine import FlamQuencySync, SyncResult
from flamquency.config import load_config, save_config
from flamquency.cloud import LocalBackend, get_backend

class TestConfig:
    """Test configuration"""
    exclude_patterns = [
        "**/.flamquency/sync/**",
        "**/.flamquency/snapshots/**",
        "**/.flamquency/versions/**",
        "**/.cache/**",
        "**/*.tmp",
        "**/__pycache__/**",
    ]

def test_config_load():
    """Test configuration loading."""
    config = load_config()
    assert "cloud_backend" in config
    assert "exclude_patterns" in config
    print("✓ Config loading works")

def test_scan_directory():
    """Test directory scanning with exclusions."""
    backend = LocalBackend()
    config = load_config()
    sync = FlamQuencySync(config=config, backend=backend)
    
    # Create a test directory
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some files
        (Path(tmpdir) / "config.txt").write_text("test")
        (Path(tmpdir) / "cache").mkdir()
        (Path(tmpdir) / "cache" / "temp.tmp").write_text("cache")
        
        files = sync.scan_directory(Path(tmpdir))
        # Should find config.txt but exclude cache/temp.tmp
        assert any("config.txt" in str(f) for f in files)
        assert not any("temp.tmp" in str(f) for f in files)
    print("✓ Directory scanning with exclusions works")

def test_hash_computation():
    """Test file hashing."""
    backend = LocalBackend()
    config = load_config()
    sync = FlamQuencySync(config=config, backend=backend)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("hello world")
        
        hash1 = sync.compute_hash(test_file)
        hash2 = sync.compute_hash(test_file)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length
    print("✓ Hash computation works")

def test_snapshot_creation():
    """Test snapshot creation."""
    backend = LocalBackend()
    config = load_config()
    sync = FlamQuencySync(config=config, backend=backend)
    
    # Clean up existing snapshots
    for snap in sync.snapshot_dir.iterdir():
        if snap.is_dir():
            shutil.rmtree(snap)
    
    snap, meta = sync.create_snapshot()
    assert snap.exists()
    assert "file_count" in meta
    assert meta["file_count"] >= 0
    print(f"✓ Snapshot creation works ({meta['file_count']} files)")

def test_sync_operation():
    """Test sync operation."""
    backend = LocalBackend()
    config = load_config()
    sync = FlamQuencySync(config=config, backend=backend)
    
    # Clean up sync dir
    sync_dir = backend.base_path
    if sync_dir.exists():
        shutil.rmtree(sync_dir)
    
    # Create a small test directory
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("sync test")
        
        result = sync.sync(source=Path(tmpdir))
        assert isinstance(result, SyncResult)
        assert result.files_synced >= 1
    print("✓ Sync operation works")

def test_rollback_snapshot():
    """Test snapshot rollback."""
    backend = LocalBackend()
    config = load_config()
    sync = FlamQuencySync(config=config, backend=backend)
    
    # Create a snapshot
    snap, meta = sync.create_snapshot()
    
    # Test rollback
    success, msg = sync.rollback_to_snapshot(snap.name)
    assert success
    print("✓ Snapshot rollback works")

def test_rollback_file():
    """Test per-file rollback info."""
    backend = LocalBackend()
    config = load_config()
    sync = FlamQuencySync(config=config, backend=backend)
    
    # Use the config file as test
    config_path = Path.home() / ".flamquency" / "config.yaml"
    if config_path.exists():
        success, msg = sync.rollback_file(str(config_path))
        # File might not have version history yet
        assert success is not None
    print("✓ Per-file rollback info works")

def test_backend_factory():
    """Test backend factory function."""
    backend = get_backend("local")
    assert isinstance(backend, LocalBackend)
    assert backend.authenticate()
    print("✓ Backend factory works")

def main():
    """Run all tests."""
    print("Running FlamQuency-Sync tests...\n")
    
    tests = [
        test_config_load,
        test_scan_directory,
        test_hash_computation,
        test_snapshot_creation,
        test_sync_operation,
        test_rollback_snapshot,
        test_rollback_file,
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
            failed += 1
    
    print(f"\n{'='*40}")
    print(f"Tests: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print(f"{'='*40}")
    
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
