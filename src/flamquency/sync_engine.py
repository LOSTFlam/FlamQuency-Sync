"""Core synchronization engine for FlamQuency-Sync."""
import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from hermes_tools import search_files, read_file, write_file

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
        self.backend = backend or get_backend("local")
        self.snapshot_dir = Path.home() / ".flamquency" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.version_dir = Path.home() / ".flamquency" / "versions"
        self.version_dir.mkdir(parents=True, exist_ok=True)
    
    def scan_directory(self, path, exclude_patterns=None):
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
        except Exception as e:
            return None
    
    def create_snapshot(self, name=None):
        """Create a full system snapshot."""
        if name is None:
            name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        snapshot_path = self.snapshot_dir / name
        snapshot_path.mkdir(parents=True, exist_ok=True)
        
        # Copy entire home directory structure (excluding noisy files)
        home = Path.home()
        excluded = self.config.get("exclude_patterns", [])
        
        # This is a selective copy - only sync-worthy files
        for item in home.rglob('*'):
            if item.is_file() and not self._matches_pattern(str(item), excluded):
                rel = item.relative_to(home)
                dest = snapshot_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    dest.write_bytes(item.read_bytes())
                except:
                    pass  # Skip unreadable files
        
        # Save metadata
        metadata = {
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "source": str(home),
            "file_count": len(list(snapshot_path.rglob('*'))) if snapshot_path.exists() else 0,
        }
        
        (snapshot_path / ".metadata.json").write_text(json.dumps(metadata, indent=2))
        self.snapshot_created = True
        return snapshot_path, metadata
    
    def sync(self, source=None, destination=None, exclusive=False):
        """Execute synchronization."""
        if source is None:
            source = Path.home()
        if destination is None:
            destination = self.backend.base_path if hasattr(self.backend, 'base_path') else Path.home() / ".flamquency" / "sync"
        
        source = Path(source)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        
        # Scan both directories
        source_files = self.scan_directory(source, self.config.get("exclude_patterns", []))
        dest_files = self.scan_directory(destination, self.config.get("exclude_patterns", []))
        
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
                        version_path = self.version_dir / rel
                        version_path.parent.mkdir(parents=True, exist_ok=True)
                        version_info = {
                            "hash": file_hash,
                            "synced_at": datetime.now().isoformat(),
                            "source": str(src_file),
                        }
                        # Simple version tracking - could be expanded with git
                        version_file = version_path / ".version.json"
                        if not version_file.exists():
                            version_file.write_text(json.dumps([version_info], indent=2))
                        else:
                            existing = json.loads(version_file.read_text())
                            existing.append(version_info)
                            version_file.write_text(json.dumps(existing, indent=2))
                
                result.files_changed += 1 if src_file.is_file() else 0
            except Exception as e:
                result.errors.append(f"{src_file}: {e}")
        
        # Also sync any new files from destination that aren't in source
        # (for two-way sync)
        
        # Create snapshot after sync
        self.create_snapshot()
        
        result.timestamp = datetime.now().isoformat()
        return result
    
    def rollback_to_snapshot(self, snapshot_name):
        """Rollback entire system to a previous snapshot."""
        snapshot_path = self.snapshot_dir / snapshot_name
        if not snapshot_path.exists():
            return False, "Snapshot not found"
        
        # Read metadata
        metadata_path = snapshot_path / ".metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text())
        else:
            metadata = {}
        
        # Restore files
        home = Path.home()
        for item in snapshot_path.rglob('*'):
            rel = item.relative_to(snapshot_path)
            dest = home / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if item.is_file():
                try:
                    dest.write_bytes(item.read_bytes())
                except:
                    pass
        
        return True, f"Rolled back to {snapshot_name}"
    
    def rollback_file(self, file_path, version=None):
        """Rollback a specific file to a previous version."""
        file_path = Path(file_path)
        if not file_path.exists():
            return False, "File not found"
        
        # Look for version history
        version_path = self.version_dir / file_path.relative_to(Path.home())
        version_file = version_path / ".version.json"
        
        if version_file.exists():
            versions = json.loads(version_file.read_text())
            if version is None:
                # Return available versions
                return True, f"Available versions: {len(versions)}"
            elif 0 <= version < len(versions):
                target = versions[version]
                # Restore from... where? This needs a storage backend
                # For now, just report available versions
                return True, f"Version {version}: hash {target.get('hash', 'N/A')[:16]}..."
        
        # No version history - could try cloud backup
        return False, "No version history found"
    
    def status(self):
        """Get current sync status."""
        backend_status = self.backend.get_status()
        return {
            "last_sync": self.config.get("last_sync"),
            "backend": backend_status.get("backend", "local"),
            "files_synced": backend_status.get("synced_items", 0),
        }
