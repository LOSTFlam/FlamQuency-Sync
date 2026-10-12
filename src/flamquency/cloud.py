"""Cloud backend abstraction for FlamQuency-Sync."""
import os
import json
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class CloudBackend(ABC):
    """Abstract base class for cloud storage backends."""
    
    @abstractmethod
    def authenticate(self) -> bool:
        """Authenticate with the cloud service."""
        ...
    
    @abstractmethod
    def upload(self, local_path, remote_path) -> bool:
        """Upload a file or directory to cloud."""
        ...
    
    @abstractmethod
    def download(self, remote_path, local_path) -> bool:
        """Download a file or directory from cloud."""
        ...
    
    @abstractmethod
    def list_remote(self, remote_path) -> List[Path]:
        """List remote files."""
        ...
    
    @abstractmethod
    def delete_remote(self, remote_path) -> bool:
        """Delete a file from cloud."""
        ...
    
    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Get current cloud sync status."""
        ...


class LocalBackend(CloudBackend):
    """Local file storage backend."""
    
    def __init__(self, base_path=None):
        if base_path is None:
            base_path = Path.home() / ".flamquency" / "sync"
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def authenticate(self) -> bool:
        return True
    
    def upload(self, local_path, remote_path) -> bool:
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
    
    def download(self, remote_path, local_path) -> bool:
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
    
    def list_remote(self, remote_path) -> List[Path]:
        remote = self.base_path / remote_path
        if remote.exists():
            return [f.relative_to(remote) for f in remote.rglob('*') if f.is_file()]
        return []
    
    def delete_remote(self, remote_path) -> bool:
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
    
    def get_status(self) -> Dict[str, Any]:
        if self.base_path.exists():
            return {
                "backend": "local",
                "base_path": str(self.base_path),
                "synced_items": len(list(self.base_path.rglob('*'))),
            }
        return {"backend": "local", "base_path": str(self.base_path), "synced_items": 0}


def get_backend(backend_type, **kwargs):
    """Factory function to create cloud backend."""
    if backend_type == "local":
        return LocalBackend(kwargs.get('base_path'))
    elif backend_type == "github":
        from flamquency.github_backend import GitHubBackend
        return GitHubBackend(kwargs.get('repo_name'), kwargs.get('token'))
    else:
        return LocalBackend()
