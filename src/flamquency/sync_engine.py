"""Core synchronization engine for FlamQuency-Sync."""
import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from flamquency.version_store import VersionStore, BlobStore
from flamquency.cloud import LocalBackend
from flamquency.ignore import IgnoreRules, default_ignore_path
from flamquency.encryption import (
    EncryptionManager, EncryptionError, WrongPasswordError,
    EncryptionLockedError, DecryptionError,
)

# Internal FlamQuency data that must NEVER be synced (recursion guard +
# the encryption key file). These are hard excludes: not even a negation
# rule in .flamquencyignore can re-include them.
INTERNAL_EXCLUDE_PATTERNS = (
    "**/.flamquency/sync/**",
    "**/.flamquency/snapshots/**",
    "**/.flamquency/versions/**",
    "**/.flamquency/data/**",
    "**/.flamquency/encryption.json",
)

class SyncResult:
    def __init__(self):
        self.files_synced = 0
        self.files_changed = 0
        self.files_excluded = 0
        self.errors = []
        self.snapshot_created = False
        self.timestamp = datetime.now().isoformat()
        self.blobs_stored = 0
        self.profile = None    # profile name when this run followed one
        self.paths = []        # per-root breakdown: {"path", "label", "files_synced"}

class FlamQuencySync:
    """Main synchronization engine."""

    def __init__(self, config=None, backend=None, password=None, base_dir=None,
                 ignore_file=None):
        self.config = config or {}
        self.backend = backend or LocalBackend()
        self.base_dir = Path(base_dir) if base_dir else Path.home() / ".flamquency"
        self.snapshot_dir = self.base_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.encryption = self._setup_encryption(password)
        self.ignore_rules = self._setup_ignore(ignore_file)
        self.version_store = VersionStore(
            self.base_dir / "versions", encryption=self.encryption
        )
        self.version_dir = self.base_dir / "versions" / "files"
        self.version_dir.mkdir(parents=True, exist_ok=True)

    def _setup_ignore(self, ignore_file):
        """Load .flamquencyignore rules (gitignore-style syntax).

        - explicit ignore_file (tests, future --ignore flag) always wins
        - otherwise ~/.flamquencyignore is used when use_ignore_file is on
        - a missing file is simply "no rules" — never an error
        """
        if ignore_file is not None:
            return IgnoreRules.from_file(Path(ignore_file).expanduser())
        if not self.config.get("use_ignore_file", True):
            return IgnoreRules.empty()
        custom = self.config.get("ignore_file_path")
        path = Path(custom).expanduser() if custom else default_ignore_path()
        return IgnoreRules.from_file(path)

    def _setup_encryption(self, password):
        """Build the encryption manager for the version store.

        - encryption disabled in config  → None (plain store)
        - enabled + password + no key yet → enable encryption, create key file
        - enabled + password + key exists → unlock (raises WrongPasswordError)
        - enabled + no password           → locked manager (reads/writes fail)
        """
        enc_cfg = self.config.get("encryption") or {}
        if not enc_cfg.get("enabled"):
            return None

        store_dir = self.base_dir / "versions"
        manager = EncryptionManager(store_dir)
        if manager.is_configured:
            if password is None:
                return manager  # locked — operations will raise until unlocked
            manager.unlock(password)  # raises WrongPasswordError on mismatch
            return manager
        if password is None:
            raise EncryptionError(
                "Encryption is enabled but no password was provided"
            )
        return EncryptionManager.enable(store_dir, password)
    
    def _require_unlocked(self):
        """Encrypted stores must refuse to run while locked — never silently skip."""
        if self.encryption is not None and self.encryption.is_configured:
            if not self.encryption.is_unlocked:
                raise EncryptionLockedError(
                    "Blob store is encrypted but locked — "
                    "provide the password (--password / FLAMQUENCY_PASSWORD)"
                )

    def _rel_to(self, path, root):
        """POSIX-style path of `path` relative to `root` (for ignore matching)."""
        try:
            return Path(path).relative_to(Path(root)).as_posix()
        except ValueError:
            return Path(path).as_posix()

    def _is_internal(self, path_str):
        """Hard excludes — internal FlamQuency data is never syncable."""
        return self._matches_pattern(path_str, INTERNAL_EXCLUDE_PATTERNS)

    def _ignore_decision(self, path, root, is_dir=False, patterns=None):
        """The single exclusion decision for one path.

        Precedence (first hit wins):
        1. internal FlamQuency data — never negotiable
        2. .flamquencyignore rules — last matching rule wins, and a
           negation here overrides the config defaults (that's the point
           of letting users customize: "I *do* want my .log files")
        3. config exclude_patterns — the built-in defaults (or an
           explicitly passed override)
        """
        path_str = str(path)
        if self._is_internal(path_str):
            return True
        if self.ignore_rules:
            rel = self._rel_to(path, root)
            ignored, decider = self.ignore_rules.explain(rel, is_dir=is_dir)
            if decider is not None:
                return ignored
        if patterns is None:
            patterns = self.config.get("exclude_patterns", [])
        return self._matches_pattern(path_str, patterns)

    def _scan_with_stats(self, path, exclude_patterns=None, max_files=10000):
        """Walk `path` and return (kept_files, excluded_count).

        Config exclude_patterns AND .flamquencyignore rules both apply;
        ignored directories are pruned (never descended into), and every
        skipped file is counted so `sync` can report it.
        """
        if exclude_patterns is None:
            exclude_patterns = self.config.get("exclude_patterns", [])

        path = Path(path)
        if not path.exists():
            return [], 0

        files = []
        excluded = 0
        for root, dirs, filenames in os.walk(path):
            root_path = Path(root)
            kept_dirs = []
            for d in dirs:
                dir_path = root_path / d
                if self._ignore_decision(dir_path, path, is_dir=True,
                                         patterns=exclude_patterns):
                    excluded += 1
                    continue
                kept_dirs.append(d)
            dirs[:] = kept_dirs
            for filename in filenames:
                if len(files) >= max_files:
                    return files, excluded
                file_path = root_path / filename
                if self._ignore_decision(file_path, path, is_dir=False,
                                         patterns=exclude_patterns):
                    excluded += 1
                    continue
                files.append(file_path)
        return files, excluded

    def scan_directory(self, path, exclude_patterns=None, max_files=10000):
        """Public scan API — just the kept files (unchanged signature)."""
        files, _ = self._scan_with_stats(
            path, exclude_patterns=exclude_patterns, max_files=max_files
        )
        return files
    
    def _matches_pattern(self, path_str, patterns):
        import fnmatch
        for pattern in patterns:
            try:
                if fnmatch.fnmatch(path_str, pattern):
                    return True
                if fnmatch.fnmatch(Path(path_str).name, pattern):
                    return True
            except:
                continue
        return False
    
    def compute_hash(self, filepath):
        return self.version_store.blob_store.store_file(filepath)
    
    def create_snapshot(self, name=None, source_path=None, max_files=1000,
                        exclude_patterns=None):
        self._require_unlocked()
        if name is None:
            name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        snapshot_path = self.snapshot_dir / name
        snapshot_path.mkdir(parents=True, exist_ok=True)
        
        if source_path is None:
            source_path = Path.home() / ".flamquency"
        
        manifest = {}
        
        count = 0
        for item in source_path.rglob('*'):
            if count >= max_files:
                break
            if item.is_file() and not self._ignore_decision(
                    item, source_path, is_dir=False,
                    patterns=exclude_patterns):
                rel = str(item.relative_to(source_path))
                file_hash = self.version_store.blob_store.store_file(item)
                manifest[rel] = file_hash
                count += 1
        
        metadata = {
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "source": str(source_path),
            "file_count": count,
            "manifest": manifest,
        }
        
        (snapshot_path / "manifest.json").write_text(json.dumps(metadata, indent=2))
        self.snapshot_created = True
        return snapshot_path, metadata
    
    def _unique_snapshot_name(self, name):
        """Never clobber an existing snapshot — suffix _2, _3, ... if taken."""
        candidate = name
        counter = 2
        while (self.snapshot_dir / candidate).exists():
            candidate = f"{name}_{counter}"
            counter += 1
        return candidate

    def _root_label(self, path, taken):
        """Stable destination subdirectory name for one sync root."""
        label = Path(path).name or "root"
        label = label.strip()
        if not label:
            label = "root"
        # two roots with the same basename must not land in one bucket
        base = label
        counter = 2
        while label in taken:
            label = f"{base}_{counter}"
            counter += 1
        taken.add(label)
        return label

    def _sync_root(self, source, destination, label, max_files=10000,
                   exclude_patterns=None):
        """Sync one root into `destination/label`, tracking versions as `label/rel`.

        Returns a SyncResult for this root alone; sync() aggregates the
        per-root results.
        """
        source = Path(source)
        destination = Path(destination)

        source_files, excluded_count = self._scan_with_stats(
            source, exclude_patterns=exclude_patterns, max_files=max_files
        )

        result = SyncResult()
        result.files_excluded = excluded_count

        for src_file in source_files:
            rel = src_file.relative_to(source)
            # Label-prefixed keys keep version histories separate per root,
            # so two roots with an identically named file never collide.
            store_key = f"{label}/{rel.as_posix()}" if label else rel.as_posix()
            dest_file = destination / label / rel if label else destination / rel

            dest_file.parent.mkdir(parents=True, exist_ok=True)

            try:
                if src_file.is_file():
                    hash_hex, is_new = self.version_store.record_version(
                        store_key, filepath=src_file
                    )
                    if is_new:
                        result.blobs_stored += 1
                        result.files_changed += 1

                    dest_file.write_bytes(src_file.read_bytes())
                    result.files_synced += 1
            except Exception as e:
                result.errors.append(f"{src_file}: {e}")

        # One snapshot per synced root — named after the root so rollbacks
        # stay readable.
        prefix = f"snapshot_{label}_" if label else "snapshot_"
        snap_name = self._unique_snapshot_name(
            f"{prefix}{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        self.create_snapshot(name=snap_name, source_path=source,
                             max_files=max_files,
                             exclude_patterns=exclude_patterns)
        result.snapshot_created = True
        result.timestamp = datetime.now().isoformat()
        return result

    def sync(self, source=None, destination=None, max_files=10000,
             profile=None):
        """Synchronize files.

        - explicit `source`  → single root, no profile (classic behaviour)
        - otherwise          → the profile named by `profile`, or the active
                               one from the config; every path of the profile
                               is synced in turn
        """
        self._require_unlocked()

        if source is not None:
            # Explicit source wins — plain single-root sync, no profile.
            if destination is None:
                destination = self.backend.base_path
            result = self._sync_root(source, destination, label=None,
                                     max_files=max_files)
            self._finish_sync(result)
            return result

        # Profile-driven sync (explicit --profile or the active profile).
        from flamquency.profiles import (
            ProfileError, ensure_profiles, get_profile, active_name,
            profile_paths, exclude_patterns as profile_excludes,
        )
        ensure_profiles(self.config)
        name = profile if profile is not None else active_name(self.config)
        prof = get_profile(self.config, name)  # raises ProfileError if unknown

        if destination is None:
            destination = self.backend.base_path
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)

        excludes = profile_excludes(self.config, prof)
        roots = profile_paths(self.config, name)

        combined = SyncResult()
        combined.profile = name
        taken_labels = set()
        for root in roots:
            if not root.exists():
                combined.errors.append(f"{root}: path does not exist")
                continue
            label = self._root_label(root, taken_labels)
            result = self._sync_root(root, destination, label,
                                     max_files=max_files,
                                     exclude_patterns=excludes)
            combined.files_synced += result.files_synced
            combined.files_changed += result.files_changed
            combined.files_excluded += result.files_excluded
            combined.blobs_stored += result.blobs_stored
            combined.errors.extend(result.errors)
            combined.snapshot_created = combined.snapshot_created or result.snapshot_created
            combined.paths.append({
                "path": str(root),
                "label": label,
                "files_synced": result.files_synced,
            })

        self._finish_sync(combined)
        combined.timestamp = datetime.now().isoformat()
        return combined

    def _finish_sync(self, result):
        """Bookkeeping shared by every sync flavour: stamp last_sync, save."""
        self.config["last_sync"] = datetime.now().isoformat()
        from flamquency.config import save_config
        # Save into this engine's base dir (== ~/.flamquency by default),
        # so isolated instances never touch the real user config.
        save_config(self.config, config_path=self.base_dir / "config.yaml")
        result.timestamp = datetime.now().isoformat()
        return result
    
    def _find_rel_path(self, file_path):
        """Try to find a relative path key that exists in version store."""
        file_path = str(file_path)
        # Try direct match
        if self.version_store.get_history(file_path):
            return file_path
        
        # Try basename
        basename = Path(file_path).name
        if self.version_store.get_history(basename):
            return basename
        
        # Try just the filename without extension
        stem = Path(file_path).stem
        if self.version_store.get_history(stem):
            return stem
        
        # Try relative to common roots
        home = Path.home()
        for root in [home / ".flamquency", home]:
            try:
                rel = str(Path(file_path).relative_to(root))
                if self.version_store.get_history(rel):
                    return rel
            except ValueError:
                continue
        
        # Try any key that ends with this filename
        for vf in self.version_dir.glob("*.json"):
            key = vf.stem.replace("__", "/")
            if key.endswith(basename) or key == basename:
                return key
        
        return file_path  # Return as-is, will fail gracefully
    
    def rollback_to_snapshot(self, snapshot_name, target_path=None):
        snapshot_path = self.snapshot_dir / snapshot_name
        manifest_file = snapshot_path / "manifest.json"
        
        if not manifest_file.exists():
            return False, "Snapshot manifest not found"
        
        metadata = json.loads(manifest_file.read_text())
        manifest = metadata.get("manifest", {})
        
        if target_path is None:
            target_path = metadata.get("source", Path.home() / ".flamquency")
        target = Path(target_path)
        
        restored = 0
        for rel, hash_hex in manifest.items():
            dest = target / rel
            if self.version_store.blob_store.restore_to(hash_hex, dest):
                restored += 1
        
        return True, f"Rolled back to {snapshot_name} ({restored}/{len(manifest)} files restored)"
    
    def rollback_file(self, file_path, version_index=None):
        """Rollback a specific file to a previous version."""
        rel_str = self._find_rel_path(file_path)
        history = self.version_store.get_history(rel_str)
        
        if not history:
            return False, "No version history found for this file"
        
        if version_index is None:
            versions = self.version_store.list_versions(rel_str)
            return True, {
                "rel_path": rel_str,
                "version_count": len(versions),
                "versions": versions,
                "message": f"File has {len(versions)} version(s). Specify version_index to rollback."
            }
        
        dest = Path(file_path)
        success, msg = self.version_store.restore_version(rel_str, version_index, dest_path=dest)
        return success, msg
    
    def diff_file(self, file_path, v1, v2):
        rel_str = self._find_rel_path(file_path)
        diff = self.version_store.diff_versions(rel_str, v1, v2)
        if diff is None:
            return False, "Could not diff versions"
        return True, diff
    
    def list_snapshots(self):
        snapshots = []
        if self.snapshot_dir.exists():
            for snap in sorted(self.snapshot_dir.iterdir()):
                if snap.is_dir():
                    manifest = snap / "manifest.json"
                    if manifest.exists():
                        meta = json.loads(manifest.read_text())
                        snapshots.append({
                            "name": meta["name"],
                            "timestamp": meta["timestamp"],
                            "file_count": meta.get("file_count", 0),
                        })
                    else:
                        snapshots.append({
                            "name": snap.name,
                            "timestamp": "unknown",
                            "file_count": 0,
                        })
        return snapshots

    def prune_snapshots(self, keep_last=None, older_than_days=None):
        """Retention policy: удалить старые снапшоты.

        keep_last: оставить N последних снапшотов.
        older_than_days: удалить снапшоты старше N дней.
        Из конфига: retention.keep_last / retention.older_than_days.
        Возвращает (удалено, сообщение).
        """
        retention = (self.config.get("retention") or {})
        if keep_last is None:
            keep_last = retention.get("keep_last")
        if older_than_days is None:
            older_than_days = retention.get("older_than_days")

        if keep_last is None and older_than_days is None:
            return 0, "Retention policy not configured"

        snapshots = self.list_snapshots()  # старые → новые

        to_delete = set()
        if keep_last is not None:
            if len(snapshots) > keep_last:
                for snap in snapshots[:-keep_last]:
                    to_delete.add(snap["name"])

        if older_than_days is not None:
            cutoff = datetime.now() - timedelta(days=older_than_days)
            for snap in snapshots:
                try:
                    ts = datetime.fromisoformat(snap["timestamp"])
                except (ValueError, TypeError):
                    continue
                if ts < cutoff:
                    to_delete.add(snap["name"])

        deleted = 0
        for name in sorted(to_delete):
            snap_path = self.snapshot_dir / name
            if snap_path.exists():
                import shutil
                shutil.rmtree(snap_path)
                deleted += 1

        if deleted:
            return deleted, f"Pruned {deleted} snapshot(s)"
        return 0, "Nothing to prune"
    
    def status(self):
        backend_status = self.backend.get_status()
        vs_stats = self.version_store.stats()
        if self.encryption is None:
            enc_state = "disabled"
        elif self.encryption.is_unlocked:
            enc_state = "enabled"
        else:
            enc_state = "locked"
        ignore_file = None
        if self.ignore_rules and self.ignore_rules.path:
            ignore_file = str(self.ignore_rules.path)
        from flamquency.profiles import ensure_profiles, profile_names, active_name
        ensure_profiles(self.config)
        return {
            "last_sync": self.config.get("last_sync"),
            "backend": backend_status.get("backend", "local"),
            "files_synced": backend_status.get("synced_items", 0),
            "tracked_files": vs_stats.get("tracked_files", 0),
            "blob_count": vs_stats.get("blob_count", 0),
            "storage_bytes": vs_stats.get("stored_bytes", 0),
            "encryption": enc_state,
            "encrypted_blobs": vs_stats.get("encrypted_blobs", 0),
            "ignore_rules": len(self.ignore_rules),
            "ignore_file": ignore_file,
            "active_profile": active_name(self.config),
            "profiles": profile_names(self.config),
            "profile_count": len(self.config["profiles"]),
        }
