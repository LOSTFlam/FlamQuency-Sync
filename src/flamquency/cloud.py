"""Cloud backend abstraction for FlamQuency-Sync."""
import os
import json
from pathlib import Path
from abc import ABC, abstractmethod

class CloudBackend(ABC):
    """Abstract base class for cloud storage backends."""
    
    @abstractmethod
    def authenticate(self):
        """Authenticate with the cloud service."""
        pass
    
    @abstractmethod
    def upload(self, local_path, remote_path):
        """Upload a file or directory to cloud."""
        pass
    
    @abstractmethod
    def download(self, remote_path, local_path):
        """Download a file or directory from cloud."""
        pass
    
    @abstractmethod
    def list_remote(self, remote_path):
        """List remote files."""
        pass
    
    @abstractmethod
    def delete_remote(self, remote_path):
        """Delete a file from cloud."""
        pass
    
    @abstractmethod
    def get_status(self):
        """Get current cloud sync status."""
        pass

class LocalBackend(CloudBackend):
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
            remote.unlink() if remote.is_file() else self._rmtree(remote)
            return True
        return False
    
    def _rmtree(self, path):
        """Remove directory tree."""
        for item in path.rglob('*'):
            item.unlink() if item.is_file() else None
        path.rmdir()
    
    def get_status(self):
        """Get local sync status."""
        return {
            "backend": "local",
            "base_path": str(self.base_path),
            "synced_items": len(list(self.base_path.rglob('*'))) if self.base_path.exists() else 0,
        }

class GitHubBackend(CloudBackend):
    """GitHub repository backend."""
    
    def __init__(self, repo_name=None, token=None):
        self.repo_name = repo_name
        self.token = token
        self.github = None
        self.repo = None
    
    def authenticate(self):
        """Authenticate with GitHub using token."""
        try:
            import ghapi
            self.github = ghapi.GitHub(self.token)
            return True
        except ImportError:
            # Try git remote approach
            return False
    
    def _ensure_repo(self, username):
        """Create or find the FlamQuency sync repo."""
        import subprocess
        # Check if repo exists
        try:
            result = subprocess.run(
                ['gh', 'repo', 'view', self.repo_name],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                self.repo = self.repo_name
                return True
        except:
            pass
        
        # Create new repo
        try:
            subprocess.run(
                ['gh', 'repo', 'create', self.repo_name,
                 '--private', '--source', '.',
                 '--push'],
                capture_output=True, text=True, cwd=Path.home()
            )
            self.repo = self.repo_name
            return True
        except Exception as e:
            print(f"GitHub repo creation failed: {e}")
            return False
    
    def upload(self, local_path, remote_path):
        """Upload via git."""
        # This is simplified - real implementation would use git operations
        print(f"GitHub upload: {local_path} -> {remote_path}")
        return True
    
    def download(self, remote_path, local_path):
        """Download via git pull."""
        print(f"GitHub download: {remote_path} -> {local_path}")
        return True
    
    def list_remote(self, remote_path):
        """List git repo contents."""
        return []
    
    def delete_remote(self, remote_path):
        """Delete from git."""
        return True
    
    def get_status(self):
        """Get GitHub sync status."""
        return {
            "backend": "github",
            "repo": self.repo_name,
            "status": "not_implemented",
        }

class GoogleDriveBackend(CloudBackend):
    """Google Drive backend (simplified)."""
    
    def __init__(self, credentials_path=None):
        self.credentials_path = credentials_path
        self.service = None
    
    def authenticate(self):
        """Authenticate with Google Drive via OAuth."""
        print("Google Drive OAuth flow would start here...")
        return False  # Simplified for now
    
    def upload(self, local_path, remote_path):
        """Upload to Google Drive."""
        print(f"Google Drive upload: {local_path} -> {remote_path}")
        return True
    
    def download(self, remote_path, local_path):
        """Download from Google Drive."""
        print(f"Google Drive download: {remote_path} -> {local_path}")
        return True
    
    def list_remote(self, remote_path):
        """List Google Drive files."""
        return []
    
    def delete_remote(self, remote_path):
        """Delete from Google Drive."""
        return True
    
    def get_status(self):
        """Get Google Drive status."""
        return {
            "backend": "google_drive",
            "status": "not_implemented",
        }

def get_backend(backend_type, **kwargs):
    """Factory function to create cloud backend."""
    if backend_type == "local":
        return LocalBackend(kwargs.get('base_path'))
    elif backend_type == "github":
        return GitHubBackend(kwargs.get('repo_name'), kwargs.get('token'))
    elif backend_type == "google_drive":
        return GoogleDriveBackend(kwargs.get('credentials_path'))
    else:
        return LocalBackend()
