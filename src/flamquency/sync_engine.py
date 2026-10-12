"""Core synchronization engine for FlamQuency-Sync."""
import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from flamquency.version_store import VersionStore, BlobStore
from flamquency.cloud import LocalBackend

class SyncResult:
    def __init__(self):
        self.files_synced = 0
        self.files_changed = 0
        self.files_excluded = 0
        self.errors = []
        self.snapshot_created = False
        self.timestamp = datetime.now().isoformat()
        self.blobs_stored = 0

class FlamQuencySync:
    """Main synchronization engine."""
    
    def __init__(self, config=None, backend=None):
        self.config = config or {}
        self.backend = backend or LocalBackend()
        self.base_dir = Path.home() / ".flamquency"
        self.snapshot_dir = self.base_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.version_store = VersionStore(self.base_dir / "versions")
        self.version_dir = self.base_dir / "versions" / "files"
        self.version_dir.mkdir(parents=True, exist_ok=True)
    
    def scan_directory(self, path, exclude_patterns=None, max_files=10000):
        if exclude_patterns is None:
            exclude_patterns = self.config.get("exclude_patterns", [])
        
        path = Path(path)
        if not path.exists():
            return []
        
        files = []
        for root, dirs, filenames in os.walk(path):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if not self._matches_pattern(
                str(root_path / d), exclude_patterns)]
            for filename in filenames:
                if len(files) >= max_files:
                    return files
                file_path = root_path / filename
                if not self._matches_pattern(str(file_path), exclude_patterns):
                    files.append(file_path)
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
    
    def create_snapshot(self, name=None, source_path=None, max_files=1000):
        if name is None:
            name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        snapshot_path = self.snapshot_dir / name
        snapshot_path.mkdir(parents=True, exist_ok=True)
        
        if source_path is None:
            source_path = Path.home() / ".flamquency"
        
        excluded = self.config.get("exclude_patterns", [])
        manifest = {}
        
        count = 0
        for item in source_path.rglob('*'):
            if count >= max_files:
                break
            if item.is_file() and not self._matches_pattern(str(item), excluded):
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
    
    def sync(self, source=None, destination=None, max_files=10000):
        if source is None:
            source = Path.home() / ".flamquency"
        if destination is None:
            destination = self.backend.base_path
        
        source = Path(source)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        
        source_files = self.scan_directory(source, self.config.get("exclude_patterns", []), max_files=max_files)
        
        result = SyncResult()
        
        for src_file in source_files:
            rel = src_file.relative_to(source)
            dest_file = destination / rel
            
            if self._matches_pattern(str(src_file), self.config.get("exclude_patterns", [])):
                result.files_excluded += 1
                continue
            
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                if src_file.is_file():
                    hash_hex, is_new = self.version_store.record_version(
                        str(rel), filepath=src_file
                    )
                    if is_new:
                        result.blobs_stored += 1
                        result.files_changed += 1
                    
                    dest_file.write_bytes(src_file.read_bytes())
                    result.files_synced += 1
            except Exception as e:
                result.errors.append(f"{src_file}: {e}")
        
        self.create_snapshot(source_path=source, max_files=max_files)
        self.config["last_sync"] = datetime.now().isoformat()
        
        from flamquency.config import save_config
        save_config(self.config)
        
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
    
    def status(self):
        backend_status = self.backend.get_status()
        vs_stats = self.version_store.stats()
        return {
            "last_sync": self.config.get("last_sync"),
            "backend": backend_status.get("backend", "local"),
            "files_synced": backend_status.get("synced_items", 0),
            "tracked_files": vs_stats.get("tracked_files", 0),
            "blob_count": vs_stats.get("blob_count", 0),
            "storage_bytes": vs_stats.get("stored_bytes", 0),
        }
