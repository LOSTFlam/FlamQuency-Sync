"""Core synchronization engine for FlamQuency-Sync."""
import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime

class SyncResult:
    """Results from a sync operation."""
    def __init__(self):
        self.files_synced = 0
        self.files_changed = 0
        self.files_excluded = 0
        self.errors = []
        self.snapshot_created = False
        self.timestamp = datetime.now().isoformat()

class FlamQuencySync:
    """Main synchronization engine."""
    
    def __init__(self, config=None, backend=None):
        self.config = config or {}
        self.backend = backend or LocalBackend()
        self.snapshot_dir = Path.home() / ".flamquency" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.version_dir = Path.home() / ".flamquency" / "versions"
        self.version_dir.mkdir(parents=True, exist_ok=True)
    
    def scan_directory(self, path, exclude_patterns=None, max_files=10000):
        """Scan directory, applying exclusion patterns."""
        if exclude_patterns is None:
            exclude_patterns = self.config.get("exclude_patterns", [])
        
        path = Path(path)
        if not path.exists():
            return []
        
        files = []
        for root, dirs, filenames in os.walk(path):
            root_path = Path(root)
            
            # Apply exclusion to directories
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
        """Check if path matches any exclusion pattern."""
        import fnmatch
        for pattern in patterns:
            try:
                if fnmatch.fnmatch(path_str, pattern):
                    return True
                # Also check basename
                if fnmatch.fnmatch(Path(path_str).name, pattern):
                    return True
            except:
                continue
        return False
    
    def compute_hash(self, filepath):
        """Compute SHA256 hash of file."""
        h = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None
    
    def create_snapshot(self, name=None, source_path=None, max_files=1000):
        """Create a snapshot of a specific directory."""
        if name is None:
            name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        snapshot_path = self.snapshot_dir / name
        snapshot_path.mkdir(parents=True, exist_ok=True)
        
        # Default to .flamquency dir if no source specified
        if source_path is None:
            source_path = Path.home() / ".flamquency"
        
        excluded = self.config.get("exclude_patterns", [])
        
        count = 0
        for item in source_path.rglob('*'):
            if count >= max_files:
                break
            if item.is_file() and not self._matches_pattern(str(item), excluded):
                rel = item.relative_to(source_path)
                dest = snapshot_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    dest.write_bytes(item.read_bytes())
                    count += 1
                except:
                    pass
        
        # Save metadata
        metadata = {
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "source": str(source_path),
            "file_count": count,
        }
        
        (snapshot_path / ".metadata.json").write_text(json.dumps(metadata, indent=2))
        self.snapshot_created = True
        return snapshot_path, metadata
    
    def sync(self, source=None, destination=None, max_files=10000):
        """Execute synchronization."""
        if source is None:
            source = Path.home() / ".flamquency"  # Default to config dir
        if destination is None:
            destination = self.backend.base_path if hasattr(self.backend, 'base_path') else Path.home() / ".flamquency" / "sync"
        
        source = Path(source)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        
        # Scan source directory
        source_files = self.scan_directory(source, self.config.get("exclude_patterns", []), max_files=max_files)
        
        result = SyncResult()
        
        # Sync source -> destination
        for src_file in source_files:
            rel = src_file.relative_to(source)
            dest_file = destination / rel
            
            # Check if file should be excluded
            if self._matches_pattern(str(src_file), self.config.get("exclude_patterns", [])):
                result.files_excluded += 1
                continue
            
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                # Copy file
                if src_file.is_file():
                    dest_file.write_bytes(src_file.read_bytes())
                    result.files_synced += 1
                    
                    # Hash for version tracking
                    file_hash = self.compute_hash(src_file)
                    if file_hash:
                        # Store version info
                        rel_str = str(rel)
                        version_path = self.version_dir / rel_str
                        version_path.parent.mkdir(parents=True, exist_ok=True)
                        version_file = version_path / ".version.json"
                        
                        version_info = {
                            "hash": file_hash,
                            "synced_at": datetime.now().isoformat(),
                        }
                        
                        if version_file.exists():
                            existing = json.loads(version_file.read_text())
                            existing.append(version_info)
                            version_file.write_text(json.dumps(existing, indent=2))
                        else:
                            version_file.write_text(json.dumps([version_info], indent=2))
                
                result.files_changed += 1 if src_file.is_file() else 0
            except Exception as e:
                result.errors.append(f"{src_file}: {e}")
        
        # Create snapshot after sync
        self.create_snapshot(source_path=source, max_files=max_files)
        
        result.timestamp = datetime.now().isoformat()
        return result
    
    def rollback_to_snapshot(self, snapshot_name, target_path=None):
        """Rollback to a previous snapshot."""
        snapshot_path = self.snapshot_dir / snapshot_name
        if not snapshot_path.exists():
            return False, "Snapshot not found"
        
        # Read metadata
        metadata_path = snapshot_path / ".metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text())
        else:
            metadata = {}
        
        # Determine restore target
        if target_path is None:
            target_path = metadata.get("source", Path.home() / ".flamquency")
        target = Path(target_path)
        
        # Restore files
        restored = 0
        for item in snapshot_path.rglob('*'):
            rel = item.relative_to(snapshot_path)
            if str(rel) == ".metadata.json":
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if item.is_file():
                try:
                    dest.write_bytes(item.read_bytes())
                    restored += 1
                except:
                    pass
        
        return True, f"Rolled back to {snapshot_name} ({restored} files restored)"
    
    def rollback_file(self, file_path, version=None):
        """Rollback a specific file to a previous version."""
        file_path = Path(file_path)
        
        # Look for version history relative to common roots
        possible_roots = [
            Path.home() / ".flamquency",
            Path.home(),
        ]
        
        rel_str = None
        for root in possible_roots:
            try:
                rel_str = str(file_path.relative_to(root))
                break
            except ValueError:
                continue
        
        if rel_str is None:
            rel_str = str(file_path)
        
        version_path = self.version_dir / rel_str
        version_file = version_path / ".version.json"
        
        if version_file.exists():
            versions = json.loads(version_file.read_text())
            if version is None:
                return True, f"File has {len(versions)} version(s) recorded"
            elif 0 <= version < len(versions):
                target = versions[version]
                return True, f"Version {version} exists (hash: {target.get('hash', 'N/A')[:16]}...)"
        
        return False, "No version history found"
    
    def status(self):
        """Get current sync status."""
        backend_status = self.backend.get_status()
        return {
            "last_sync": self.config.get("last_sync"),
            "backend": backend_status.get("backend", "local"),
            "files_synced": backend_status.get("synced_items", 0),
        }

class LocalBackend:
    """Local file storage backend."""
    
    def __init__(self, base_path=None):
        if base_path is None:
            base_path = Path.home() / ".flamquency" / "sync"
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def authenticate(self):
        """Local backend requires no authentication."""
        return True
    
    def upload(self, local_path, remote_path):
        """Copy to local sync directory."""
        remote = self.base_path / remote_path
        if local_path.is_dir():
            remote.mkdir(parents=True, exist_ok=True)
            for item in local_path.rglob('*'):
                rel = item.relative_to(local_path)
                dest = remote / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if item.is_file():
                    dest.write_bytes(item.read_bytes())
        else:
            remote.parent.mkdir(parents=True, exist_ok=True)
            remote.write_bytes(local_path.read_bytes())
        return True
    
    def download(self, remote_path, local_path):
        """Copy from local sync directory."""
        remote = self.base_path / remote_path
        if remote.is_dir():
            local_path.mkdir(parents=True, exist_ok=True)
            for item in remote.rglob('*'):
                rel = item.relative_to(remote)
                dest = local_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if item.is_file():
                    dest.write_bytes(item.read_bytes())
        else:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(remote.read_bytes())
        return True
    
    def list_remote(self, remote_path):
        """List files in local sync directory."""
        remote = self.base_path / remote_path
        if remote.exists():
            return [f.relative_to(remote) for f in remote.rglob('*') if f.is_file()]
        return []
    
    def delete_remote(self, remote_path):
        """Remove from local sync directory."""
        remote = self.base_path / remote_path
        if remote.exists():
            if remote.is_file():
                remote.unlink()
            else:
                for item in remote.rglob('*'):
                    item.unlink()
                remote.rmdir()
            return True
        return False
    
    def get_status(self):
        """Get local sync status."""
        if self.base_path.exists():
            return {
                "backend": "local",
                "base_path": str(self.base_path),
                "synced_items": len(list(self.base_path.rglob('*'))),
            }
        return {"backend": "local", "base_path": str(self.base_path), "synced_items": 0}
