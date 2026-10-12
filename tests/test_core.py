#!/usr/bin/env python3
"""Test suite for FlamQuency-Sync."""
import sys
import os
import tempfile
import shutil
import json
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flamquency.sync_engine import FlamQuencySync, SyncResult, LocalBackend
from flamquency.config import load_config, save_config
from flamquency.version_store import VersionStore, BlobStore
from flamquency.cloud import get_backend
from flamquency.encryption import (
    EncryptionManager, EncryptionError, EncryptionLockedError,
    WrongPasswordError, DecryptionError,
)

ENC_PW = "correct horse battery staple"


def _isolated_sync(tmpdir, config=None, password=None):
    """Create a FlamQuencySync with isolated storage in a temp dir."""
    if config is None:
        config = load_config()
    base = Path(tmpdir) / ".flamquency_isolated"
    backend = LocalBackend(base_path=base / "sync")
    return FlamQuencySync(
        config=config, backend=backend, password=password, base_dir=base
    )


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


# ── Encryption ────────────────────────────────────────────────

def test_encryption_enable_unlock_and_wrong_password():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "store"
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        assert mgr.is_configured
        assert mgr.is_unlocked
        assert mgr.key_path.exists()

        # Unlock with the correct password
        mgr2 = EncryptionManager(base)
        assert mgr2.is_configured
        assert not mgr2.is_unlocked
        mgr2.unlock(ENC_PW)
        assert mgr2.is_unlocked

        # Wrong password must be rejected
        mgr3 = EncryptionManager(base)
        try:
            mgr3.unlock("not the password")
            assert False, "wrong password should raise WrongPasswordError"
        except WrongPasswordError:
            pass
        assert not mgr3.is_unlocked

        # Lock / unlock cycle
        mgr2.lock()
        assert not mgr2.is_unlocked
        mgr2.unlock(ENC_PW)
        assert mgr2.is_unlocked
    print("✓ Encryption enable/unlock/wrong-password works")


def test_encryption_encrypt_decrypt_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = EncryptionManager.enable(Path(tmpdir), ENC_PW, iterations=50_000)
        data = b"top secret payload \x00\x01\x02" * 100
        token = mgr.encrypt(data)
        assert token != data
        assert b"top secret" not in token
        assert mgr.decrypt(token) == data

        # Tampered ciphertext must not decrypt
        tampered = bytearray(token)
        tampered[-1] ^= 0xFF
        try:
            mgr.decrypt(bytes(tampered))
            assert False, "tampered token should raise DecryptionError"
        except DecryptionError:
            pass

        # Locked manager refuses to work
        mgr.lock()
        try:
            mgr.encrypt(b"x")
            assert False, "locked manager should raise EncryptionLockedError"
        except EncryptionLockedError:
            pass
        try:
            mgr.decrypt(token)
            assert False, "locked manager should raise EncryptionLockedError"
        except EncryptionLockedError:
            pass
    print("✓ Encryption encrypt/decrypt roundtrip and tamper detection work")


def test_blob_store_encrypted_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        bs = BlobStore(base, encryption=mgr)

        h = bs.store("secret blob content")
        assert len(h) == 64
        # On-disk bytes must not contain the plaintext
        raw = bs._blob_path(h).read_bytes()
        assert b"secret blob content" not in raw
        assert bs.retrieve(h) == b"secret blob content"
        # Dedup still works (same content → same hash, no second blob)
        h2 = bs.store("secret blob content")
        assert h2 == h

        # store_file + restore_to with binary data
        src = base / "blob.bin"
        payload = bytes(range(256)) * 4096  # 1 MB, non-compressible
        src.write_bytes(payload)
        hf = bs.store_file(src)
        assert b"secret" not in bs._blob_path(hf).read_bytes()[:64]
        assert payload not in bs._blob_path(hf).read_bytes()
        dest = base / "restored.bin"
        assert bs.restore_to(hf, dest)
        assert dest.read_bytes() == payload
        assert bs.stats()["blob_count"] == 2
    print("✓ Encrypted blob store roundtrip works (blobs not plaintext on disk)")


def test_blob_store_encrypted_locked_and_unlocked_read():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        bs = BlobStore(base, encryption=mgr)
        h = bs.store("hidden data")

        # Reopen without a password — store is locked
        locked_mgr = EncryptionManager(base)
        bs_locked = BlobStore(base, encryption=locked_mgr)
        try:
            bs_locked.retrieve(h)
            assert False, "locked store should raise EncryptionLockedError"
        except EncryptionLockedError:
            pass
        # And it must refuse to write plaintext into an encrypted store
        try:
            bs_locked.store("sneaky plaintext")
            assert False, "locked store should refuse new writes"
        except EncryptionLockedError:
            pass

        # Unlock with the right password → reads work again
        locked_mgr.unlock(ENC_PW)
        assert bs_locked.retrieve(h) == b"hidden data"
    print("✓ Locked encrypted store blocks reads and writes until unlocked")


def test_version_store_with_encryption():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        vs = VersionStore(base, encryption=mgr)

        vs.record_version("docs/secret.txt", data="version 1 secret")
        vs.record_version("docs/secret.txt", data="version 2 secret")
        assert len(vs.get_history("docs/secret.txt")) == 2

        dest = base / "restored.txt"
        success, msg = vs.restore_version("docs/secret.txt", 0, dest_path=dest)
        assert success
        assert dest.read_text() == "version 1 secret"

        diff = vs.diff_versions("docs/secret.txt", 0, 1)
        assert "version 2 secret" in diff
    print("✓ Version store works end-to-end with encryption")


def test_encryption_change_password():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        bs = BlobStore(base, encryption=mgr)
        h = bs.store("keep me safe")

        new_pw = "brand new password"
        new_mgr = mgr.change_password(new_pw)
        assert new_mgr.is_unlocked
        # Old password no longer opens the store
        try:
            EncryptionManager(base).unlock(ENC_PW)
            assert False, "old password should stop working"
        except WrongPasswordError:
            pass
        # Blobs were re-keyed: readable with the new password only
        bs.rekey(mgr, new_mgr)
        reopened = BlobStore(base, encryption=EncryptionManager(base))
        reopened.encryption.unlock(new_pw)
        assert reopened.retrieve(h) == b"keep me safe"
    print("✓ Password change re-keys the store")


def test_encryption_disable_decrypts_blobs():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        bs = BlobStore(base, encryption=mgr)
        h1 = bs.store("first secret")
        h2 = bs.store("second secret")

        decrypted = bs.disable_encryption(mgr)
        assert decrypted == 2
        assert not mgr.is_configured  # key file removed
        # Blobs are plaintext on disk again
        assert b"first secret" in zlib.decompress(bs._blob_path(h1).read_bytes())
        # Store works without any encryption manager
        bs_plain = BlobStore(base)
        assert bs_plain.retrieve(h1) == b"first secret"
        assert bs_plain.retrieve(h2) == b"second secret"
    print("✓ Disabling encryption decrypts existing blobs")


def test_sync_engine_with_encryption():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        config["encryption"] = {"enabled": True}
        t = Path(tmpdir)
        (t / "secret.txt").write_text("my secret notes")

        sync = _isolated_sync(tmpdir, config=config, password=ENC_PW)
        result = sync.sync(source=t)
        assert result.files_synced >= 1
        assert not result.errors, result.errors

        # Blob on disk must be ciphertext
        history = sync.version_store.get_history("secret.txt")
        assert len(history) == 1
        raw = sync.version_store.blob_store._blob_path(history[0]["hash"]).read_bytes()
        assert b"my secret notes" not in raw

        # Rollback still works through the cipher
        test_file = t / "secret.txt"
        test_file.write_text("changed!")
        sync.sync(source=t)
        success, msg = sync.rollback_file(str(test_file), version_index=0)
        assert success, msg
        assert test_file.read_text() == "my secret notes"

        # Status reports encryption state
        assert sync.status()["encryption"] == "enabled"
    print("✓ Sync engine with encryption works (ciphertext blobs + rollback)")


def test_sync_engine_wrong_password_rejected():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        config["encryption"] = {"enabled": True}
        t = Path(tmpdir)
        (t / "secret.txt").write_text("data")

        # First run sets up the keys
        _isolated_sync(tmpdir, config=config, password=ENC_PW).sync(source=t)

        # Second run with a wrong password must fail loudly
        try:
            _isolated_sync(tmpdir, config=config, password="wrong one").sync(source=t)
            assert False, "wrong password should raise WrongPasswordError"
        except WrongPasswordError:
            pass
    print("✓ Sync engine rejects wrong encryption password")


def test_sync_engine_locked_store_refuses_to_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        config["encryption"] = {"enabled": True}
        t = Path(tmpdir)
        (t / "secret.txt").write_text("data")

        # First run sets up the keys
        _isolated_sync(tmpdir, config=config, password=ENC_PW).sync(source=t)

        # A locked store (no password) must refuse to sync — never silently
        locked = _isolated_sync(tmpdir, config=config, password=None)
        assert locked.status()["encryption"] == "locked"
        try:
            locked.sync(source=t)
            assert False, "locked store should refuse to sync"
        except EncryptionLockedError:
            pass
        try:
            locked.create_snapshot(source_path=t)
            assert False, "locked store should refuse to snapshot"
        except EncryptionLockedError:
            pass
    print("✓ Locked store refuses sync and snapshot until unlocked")


def test_sync_engine_unlock_after_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        config["encryption"] = {"enabled": True}
        t = Path(tmpdir)
        (t / "secret.txt").write_text("v1")

        _isolated_sync(tmpdir, config=config, password=ENC_PW).sync(source=t)

        locked = _isolated_sync(tmpdir, config=config, password=None)
        locked.encryption.unlock(ENC_PW)
        result = locked.sync(source=t)
        assert not result.errors, result.errors
        assert result.files_synced >= 1
    print("✓ Store works again after unlocking in-place")


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
        test_encryption_enable_unlock_and_wrong_password,
        test_encryption_encrypt_decrypt_roundtrip,
        test_blob_store_encrypted_roundtrip,
        test_blob_store_encrypted_locked_and_unlocked_read,
        test_version_store_with_encryption,
        test_encryption_change_password,
        test_encryption_disable_decrypts_blobs,
        test_sync_engine_with_encryption,
        test_sync_engine_wrong_password_rejected,
        test_sync_engine_locked_store_refuses_to_run,
        test_sync_engine_unlock_after_lock,
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
