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


def _isolated_sync(tmpdir, config=None, password=None, ignore_file=None):
    """Create a FlamQuencySync with isolated storage in a temp dir.

    Hermetic by default: the real ~/.flamquencyignore is only loaded when a
    test passes ignore_file explicitly.
    """
    if config is None:
        config = load_config()
    config = dict(config)  # copy — never mutate the caller's dict
    config["use_ignore_file"] = False
    base = Path(tmpdir) / ".flamquency_isolated"
    backend = LocalBackend(base_path=base / "sync")
    return FlamQuencySync(
        config=config, backend=backend, password=password, base_dir=base,
        ignore_file=ignore_file,
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


# ── .flamquencyignore ──────────────────────────────────────────

def test_ignore_rules_parse_skips_comments_and_blanks():
    from flamquency.ignore import IgnoreRules
    rules = IgnoreRules.from_lines([
        "# a comment", "", "   ", "*.log", "!keep.log",
        "build/", "/rooted.txt", "**/node_modules",
    ])
    assert len(rules) == 5, f"expected 5 rules, got {len(rules)}"
    raws = [r.raw for r in rules]
    assert raws == ["*.log", "!keep.log", "build/", "/rooted.txt", "**/node_modules"]
    assert not rules.rules[0].negate
    assert rules.rules[1].negate
    assert rules.rules[2].dir_only
    assert not rules.rules[2].negate
    assert rules.rules[3].anchored
    print("✓ Ignore rules parse: comments/blanks dropped, flags extracted")


def test_ignore_rules_match_semantics():
    from flamquency.ignore import IgnoreRules
    rules = IgnoreRules.from_lines([
        "*.log", "!keep.log", "build/", "/rooted.txt",
        "**/node_modules", "temp?.tmp",
    ])
    # plain name pattern matches at any depth
    assert rules.match("app.log")
    assert rules.match("logs/deep/app.log")
    # negation wins — later rule re-includes
    assert not rules.match("keep.log")
    assert not rules.match("sub/keep.log")
    # directory-only pattern
    assert rules.match("build", is_dir=True)
    assert not rules.match("build", is_dir=False)      # a *file* named build is kept
    assert rules.match("x/build/out.o")                 # contents of an ignored dir
    # anchored pattern only matches at the root
    assert rules.match("rooted.txt")
    assert not rules.match("sub/rooted.txt")
    # ** crosses directories
    assert rules.match("a/b/c/node_modules", is_dir=True)
    assert not rules.match("a/b/c/node_modules_old", is_dir=True)
    # ? matches exactly one char
    assert rules.match("temp1.tmp")
    assert not rules.match("temp12.tmp")
    print("✓ Ignore match semantics work (negation, dir-only, anchored, **, ?)")


def test_ignore_rules_last_match_wins():
    from flamquency.ignore import IgnoreRules
    rules = IgnoreRules.from_lines(["*.txt", "!notes.txt", "*.txt"])
    # the last matching rule decides — re-excluded
    assert rules.match("notes.txt")
    rules2 = IgnoreRules.from_lines(["*.txt", "!notes.txt"])
    assert not rules2.match("notes.txt")
    # no rule matches → not ignored
    assert not rules2.match("photo.png")
    print("✓ Ignore rules: last matching rule wins, default is include")


def test_ignore_rules_from_file_and_missing_file():
    from flamquency.ignore import IgnoreRules
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / ".flamquencyignore"
        p.write_text("# my rules\n\n*.bak\nsecret/\n")
        rules = IgnoreRules.from_file(p)
        assert len(rules) == 2
        assert rules.match("old.bak")
        assert rules.match("secret", is_dir=True)
        assert rules.path == p
        # a missing file is simply "no rules" — never an error
        missing = IgnoreRules.from_file(Path(tmpdir) / "nope")
        assert len(missing) == 0
        assert not missing.match("anything")
    print("✓ Ignore rules load from file; missing file = no rules")


def test_ignore_rules_explain_reports_matching_rule():
    from flamquency.ignore import IgnoreRules
    rules = IgnoreRules.from_lines(["*.log", "!keep.log"])
    ignored, rule = rules.explain("app.log")
    assert ignored
    assert rule is not None and rule.raw == "*.log"
    ignored2, rule2 = rules.explain("keep.log")
    assert not ignored2
    assert rule2 is not None and rule2.raw == "!keep.log"
    ignored3, rule3 = rules.explain("photo.png")
    assert not ignored3
    assert rule3 is None
    print("✓ Ignore explain() reports which rule decided")


def test_default_ignore_template_written():
    from flamquency.ignore import (
        IGNORE_FILENAME, IgnoreRules, default_template, write_default_ignore_file,
    )
    assert IGNORE_FILENAME == ".flamquencyignore"
    text = default_template()
    assert text.startswith("#")
    assert "*.log" in text and "!keep.log" in text
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / IGNORE_FILENAME
        write_default_ignore_file(p)
        assert p.exists()
        # the written file must be valid rules that actually ignore things
        rules = IgnoreRules.from_file(p)
        assert len(rules) > 5
        assert rules.match("debug.log")
        # writing again refuses to clobber an existing file
        before = p.read_text()
        write_default_ignore_file(p)
        assert p.read_text() == before
    print("✓ Default ignore template is written once and stays valid")


def test_engine_without_ignore_file_has_no_rules():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir, ignore_file=Path(tmpdir) / "absent")
        assert len(sync.ignore_rules) == 0
        assert not sync.ignore_rules.match("whatever.log")
        assert sync.status()["ignore_rules"] == 0
        assert sync.status()["ignore_file"] is None
    print("✓ Engine without an ignore file behaves exactly as before")


def test_scan_directory_respects_ignore_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        ig = t / ".flamquencyignore"
        ig.write_text("*.log\n!keep.log\nbuild/\n/rooted.txt\n")
        sync = _isolated_sync(tmpdir, ignore_file=ig)

        (t / "notes.txt").write_text("keep me")
        (t / "debug.log").write_text("noise")
        (t / "keep.log").write_text("important")
        (t / "rooted.txt").write_text("root")
        (t / "sub").mkdir()
        (t / "sub" / "rooted.txt").write_text("nested ok")
        (t / "build").mkdir()
        (t / "build" / "out.o").write_text("artifact")
        (t / "junk.tmp").write_text("config-excluded")

        files = sync.scan_directory(t)
        names = {f.name for f in files}
        assert "notes.txt" in names
        assert "debug.log" not in names        # ignored by *.log
        assert "keep.log" in names             # re-included by !keep.log
        # anchored rule hits only the root copy, not the nested one
        assert (t / "rooted.txt") not in files
        assert (t / "sub" / "rooted.txt") in files
        assert not any("out.o" in str(f) for f in files)  # build/ pruned as a directory
        assert not any("junk.tmp" in str(f) for f in files)  # config exclude still wins
    print("✓ scan_directory honors .flamquencyignore rules")


def test_sync_counts_ignored_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        ig = t / ".flamquencyignore"
        ig.write_text("*.log\nbuild/\n")
        sync = _isolated_sync(tmpdir, ignore_file=ig)

        (t / "a.txt").write_text("hello")
        (t / "b.log").write_text("noise")
        (t / "build").mkdir()
        (t / "build" / "c.o").write_text("artifact")

        result = sync.sync(source=t)
        assert result.files_synced >= 1
        assert not result.errors, result.errors
        # ignored files are counted, not silently dropped
        assert result.files_excluded >= 2, result.files_excluded
        dest = sync.backend.base_path
        assert (dest / "a.txt").exists()
        assert not (dest / "b.log").exists()
        assert not (dest / "build").exists()
    print("✓ sync counts ignored files and never copies them")


def test_snapshot_respects_ignore_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        ig = t / ".flamquencyignore"
        ig.write_text("*.secret\n")
        sync = _isolated_sync(tmpdir, ignore_file=ig)

        (t / "public.txt").write_text("fine")
        (t / "private.secret").write_text("nope")

        snap, meta = sync.create_snapshot(source_path=t)
        manifest = meta["manifest"]
        assert "public.txt" in manifest
        assert not any("private.secret" in k for k in manifest)
    print("✓ create_snapshot honors .flamquencyignore rules")


def test_cli_ignore_init_and_check():
    import io
    import contextlib
    from argparse import Namespace
    from flamquency.cli import cmd_ignore

    with tempfile.TemporaryDirectory() as tmpdir:
        ig = Path(tmpdir) / ".flamquencyignore"

        # --init writes the default template
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=True, force=False,
                                      add=None, check=None, list=False))
        assert rc == 0
        assert ig.exists()
        assert "*.log" in ig.read_text()

        # --check reports the decision for a path
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=False, force=False,
                                      add=None, check="debug.log", list=False))
        out = buf.getvalue()
        assert rc == 0
        assert "ignored" in out.lower()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=False, force=False,
                                      add=None, check="notes.txt", list=False))
        out = buf.getvalue()
        assert rc == 0
        assert "not ignored" in out.lower()

        # --add appends a pattern and it takes effect
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=False, force=False,
                                      add="*.huge", check=None, list=False))
        assert rc == 0
        rules_text = ig.read_text()
        assert "*.huge" in rules_text

        # --list prints the loaded rules
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=False, force=False,
                                      add=None, check=None, list=True))
        out = buf.getvalue()
        assert rc == 0
        assert "*.huge" in out and "*.log" in out
    print("✓ CLI `flamquency ignore` init/add/check/list works")


# ── Sync profiles ─────────────────────────────────────────────

def _profile_engine(tmpdir, **config_overrides):
    """Isolated engine whose config carries a profiles section."""
    config = load_config()
    config = dict(config)
    config["use_ignore_file"] = False
    config.update(config_overrides)
    base = Path(tmpdir) / ".flamquency_isolated"
    backend = LocalBackend(base_path=base / "sync")
    return FlamQuencySync(config=config, backend=backend, base_dir=base)


def test_config_defaults_not_shared_between_loads():
    config = load_config()
    config["profiles"]["leak"] = {"paths": ["/leak"]}
    config["exclude_patterns"].append("*.leak")
    fresh = load_config()
    assert "leak" not in fresh.get("profiles", {})
    assert "*.leak" not in fresh["exclude_patterns"]
    print("✓ Config defaults are deep-copied — one load never mutates another")


def test_profiles_default_in_config():
    from flamquency.profiles import DEFAULT_PROFILE_NAME
    config = load_config()
    assert DEFAULT_PROFILE_NAME in config.get("profiles", {})
    assert config.get("active_profile") == DEFAULT_PROFILE_NAME
    print("✓ Config ships a default sync profile")


def test_profile_create_list_and_delete():
    from flamquency.profiles import (
        ProfileError, create_profile, delete_profile, get_profile, profile_names,
    )
    config = load_config()
    profile = create_profile(config, "documents",
                             ["~/Documents", "~/Notes"], description="docs")
    assert profile["paths"] == [str(Path.home() / "Documents"),
                                str(Path.home() / "Notes")]
    assert "documents" in profile_names(config)
    assert get_profile(config, "documents")["description"] == "docs"

    # duplicate name is refused
    try:
        create_profile(config, "documents", ["~/x"])
        assert False, "duplicate profile should raise ProfileError"
    except ProfileError:
        pass
    # a profile needs at least one path
    try:
        create_profile(config, "empty", [])
        assert False, "empty profile should raise ProfileError"
    except ProfileError:
        pass
    # unknown profile is refused
    try:
        get_profile(config, "nope")
        assert False, "unknown profile should raise ProfileError"
    except ProfileError:
        pass
    # invalid names are refused
    for bad in ["", "   ", "a/b"]:
        try:
            create_profile(config, bad, ["~/x"])
            assert False, f"invalid name {bad!r} should raise ProfileError"
        except ProfileError:
            pass

    delete_profile(config, "documents")
    assert "documents" not in profile_names(config)
    # the default profile is structural — it cannot be deleted
    try:
        delete_profile(config, "default")
        assert False, "default profile should not be deletable"
    except ProfileError:
        pass
    print("✓ Profile create/list/delete with validation works")


def test_profile_paths_and_active_switching():
    from flamquency.profiles import (
        ProfileError, active_name, add_path, create_profile, delete_profile,
        get_profile, remove_path, set_active,
    )
    config = load_config()
    home = str(Path.home())

    add_path(config, "default", "~/code")
    assert f"{home}/code" in get_profile(config, "default")["paths"]
    # adding the same path twice is a no-op (dedupe)
    add_path(config, "default", "~/code")
    assert get_profile(config, "default")["paths"].count(f"{home}/code") == 1

    remove_path(config, "default", "~/code")
    assert f"{home}/code" not in get_profile(config, "default")["paths"]
    # removing a path the profile does not have
    try:
        remove_path(config, "default", "~/nowhere")
        assert False, "removing an absent path should raise ProfileError"
    except ProfileError:
        pass
    # the last path of a profile cannot be removed
    try:
        remove_path(config, "default", "~/.flamquency")
        assert False, "a profile must keep at least one path"
    except ProfileError:
        pass

    create_profile(config, "work", ["~/projects"])
    set_active(config, "work")
    assert active_name(config) == "work"
    # the active profile cannot be deleted
    try:
        delete_profile(config, "work")
        assert False, "deleting the active profile should raise ProfileError"
    except ProfileError:
        pass
    # switching to an unknown profile
    try:
        set_active(config, "ghost")
        assert False, "unknown profile should raise ProfileError"
    except ProfileError:
        pass
    # a dangling active_profile falls back to default
    config["active_profile"] = "ghost"
    assert active_name(config) == "default"
    print("✓ Profile path management and active switching work")


def test_profile_exclude_patterns_merge():
    from flamquency.profiles import create_profile, exclude_patterns, get_profile
    config = load_config()
    create_profile(config, "media", ["~/Music"], exclude_patterns=["*.flac"])
    merged = exclude_patterns(config, get_profile(config, "media"))
    assert "*.flac" in merged            # profile extras apply
    assert "**/.git/**" in merged        # config defaults still apply
    print("✓ Profile exclude patterns merge on top of config defaults")


def test_sync_uses_active_profile_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        (docs / "a.txt").write_text("A")
        code = t / "code"; code.mkdir()
        (code / "b.txt").write_text("B")

        config = dict(load_config())
        config["use_ignore_file"] = False
        create_profile(config, "multi", [str(docs), str(code)])
        set_active(config, "multi")
        base = t / ".flamquency_isolated"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)

        result = sync.sync()
        assert result.profile == "multi"
        assert result.files_synced == 2, result.files_synced
        assert len(result.paths) == 2
        assert not result.errors, result.errors

        # each root lands under its own label — no clobbering between roots
        dest = sync.backend.base_path
        assert (dest / "docs" / "a.txt").exists()
        assert (dest / "code" / "b.txt").exists()
        # version keys are prefixed per root, so equal relative names never collide
        assert sync.version_store.get_history("docs/a.txt")
        assert sync.version_store.get_history("code/b.txt")
        # one snapshot per synced root
        assert len(sync.list_snapshots()) == 2
    print("✓ sync() follows the active profile across all its paths")


def test_sync_explicit_source_beats_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        (docs / "a.txt").write_text("A")
        other = t / "other"; other.mkdir()
        (other / "c.txt").write_text("C")

        config = dict(load_config())
        config["use_ignore_file"] = False
        create_profile(config, "multi", [str(docs)])
        set_active(config, "multi")
        base = t / ".flamquency_isolated"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)

        # an explicit --source keeps the old single-root behaviour
        result = sync.sync(source=other)
        assert result.profile is None
        assert result.files_synced == 1
        dest = sync.backend.base_path
        assert (dest / "c.txt").exists()          # no label prefix
        assert not (dest / "other").exists()
    print("✓ An explicit source overrides the active profile")


def test_sync_profile_argument_and_missing_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        (docs / "a.txt").write_text("A")

        config = dict(load_config())
        config["use_ignore_file"] = False
        create_profile(config, "work", [str(docs)])
        create_profile(config, "broken", [str(t / "ghost")])
        set_active(config, "work")
        base = t / ".flamquency_isolated"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)

        # --profile syncs that profile even when it is not the active one
        result = sync.sync(profile="work")
        assert result.profile == "work"
        assert result.files_synced == 1
        # the active profile is untouched by a one-off --profile run
        assert config["active_profile"] == "work"

        # a nonexistent path is reported, never silently skipped
        result = sync.sync(profile="broken")
        assert result.files_synced == 0
        assert result.errors and "does not exist" in result.errors[0]

        # unknown profile name
        try:
            sync.sync(profile="ghost")
            assert False, "unknown profile should raise ProfileError"
        except Exception as e:
            assert "ghost" in str(e)
    print("✓ sync(profile=...) works and missing paths are reported")


def test_status_reports_profiles():
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        config = dict(load_config())
        config["use_ignore_file"] = False
        create_profile(config, "multi", [str(docs)])
        set_active(config, "multi")
        base = t / ".flamquency_isolated"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)
        status = sync.status()
        assert status["active_profile"] == "multi"
        assert "multi" in status["profiles"]
        assert status["profile_count"] >= 2
    print("✓ status() reports the active profile and profile list")


def test_cli_profile_commands():
    import io
    import contextlib
    from argparse import Namespace
    from flamquency.cli import cmd_profile

    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        cfg = t / "config.yaml"

        def run(**kw):
            args = Namespace(
                action=kw.pop("action", "list"),
                name=kw.pop("name", None),
                path=kw.pop("path", []),
                description=kw.pop("description", ""),
                exclude=kw.pop("exclude", []),
                config_path=str(cfg),
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_profile(args)
            return rc, buf.getvalue()

        # list on a fresh config shows the default profile
        rc, out = run()
        assert rc == 0
        assert "default" in out

        # create
        rc, out = run(action="create", name="docs",
                      path=[str(t / "Documents")], description="my docs")
        assert rc == 0
        # duplicate name is refused
        rc, out = run(action="create", name="docs", path=[str(t / "x")])
        assert rc == 1
        # create without paths is refused
        rc, out = run(action="create", name="nopaths")
        assert rc == 1

        # add-path
        rc, out = run(action="add-path", name="docs", path=[str(t / "Notes")])
        assert rc == 0
        # show
        rc, out = run(action="show", name="docs")
        assert rc == 0
        assert "Documents" in out and "Notes" in out

        # use — switching the active profile
        rc, out = run(action="use", name="docs")
        assert rc == 0
        # the active profile cannot be deleted
        rc, out = run(action="delete", name="docs")
        assert rc == 1
        # switch back, then delete succeeds
        rc, out = run(action="use", name="default")
        assert rc == 0
        rc, out = run(action="delete", name="docs")
        assert rc == 0

        # unknown profile / name errors
        rc, out = run(action="show", name="ghost")
        assert rc == 1
        rc, out = run(action="use", name="ghost")
        assert rc == 1

        # config on disk reflects the operations
        config = load_config(cfg)
        assert "docs" not in config["profiles"]
        assert config["active_profile"] == "default"
    print("✓ CLI `flamquency profile` list/create/add-path/show/use/delete works")


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
        test_ignore_rules_parse_skips_comments_and_blanks,
        test_ignore_rules_match_semantics,
        test_ignore_rules_last_match_wins,
        test_ignore_rules_from_file_and_missing_file,
        test_ignore_rules_explain_reports_matching_rule,
        test_default_ignore_template_written,
        test_engine_without_ignore_file_has_no_rules,
        test_scan_directory_respects_ignore_file,
        test_sync_counts_ignored_files,
        test_snapshot_respects_ignore_file,
        test_cli_ignore_init_and_check,
        test_config_defaults_not_shared_between_loads,
        test_profiles_default_in_config,
        test_profile_create_list_and_delete,
        test_profile_paths_and_active_switching,
        test_profile_exclude_patterns_merge,
        test_sync_uses_active_profile_paths,
        test_sync_explicit_source_beats_profile,
        test_sync_profile_argument_and_missing_path,
        test_status_reports_profiles,
        test_cli_profile_commands,
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
