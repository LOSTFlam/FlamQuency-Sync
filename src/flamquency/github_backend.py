"""GitHub backend for FlamQuency-Sync — pushes snapshots to a GitHub repo."""
import os
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from flamquency.cloud import CloudBackend


class GitHubBackend(CloudBackend):
    """GitHub repository backend for cloud sync."""
    
    def __init__(self, repo_name=None, token=None, local_clone=None):
        self.repo_name = repo_name
        self.token = token
        self.local_clone = Path(local_clone) if local_clone else Path.home() / ".flamquency" / "github-clone"
        self.repo = None
    
    def authenticate(self):
        """Check gh CLI auth or token validity."""
        try:
            if self.token:
                # Validate token via API
                import urllib.request
                req = urllib.request.Request(
                    "https://api.github.com/user",
                    headers={"Authorization": f"token {self.token}"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    self.username = data.get("login", "")
                    return True
            else:
                # Use gh CLI
                result = subprocess.run(
                    ["gh", "auth", "status"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    # Get username
                    user_result = subprocess.run(
                        ["gh", "api", "user", "--jq", ".login"],
                        capture_output=True, text=True
                    )
                    self.username = user_result.stdout.strip()
                    return True
        except Exception:
            pass
        return False
    
    def _ensure_repo(self):
        """Create or clone the sync repository."""
        if not self.repo_name:
            username = getattr(self, 'username', 'user')
            self.repo_name = f"flamquency-sync-{username}"
        
        repo_full = f"{getattr(self, 'username', 'LOSTFlam')}/{self.repo_name}"
        
        # Check if repo exists
        try:
            result = subprocess.run(
                ["gh", "repo", "view", repo_full],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                # Create it
                subprocess.run(
                    ["gh", "repo", "create", self.repo_name,
                     "--private", "--description",
                     "FlamQuency-Sync automatic backup"],
                    capture_output=True, text=True
                )
        except Exception:
            pass
        
        self.repo = repo_full
        return repo_full
    
    def _ensure_clone(self):
        """Ensure local clone of the repo exists and is up to date."""
        if self.local_clone.exists() and (self.local_clone / ".git").exists():
            # Pull latest
            try:
                subprocess.run(
                    ["git", "pull", "--rebase", "origin", "master"],
                    cwd=self.local_clone, capture_output=True, text=True, timeout=30
                )
            except:
                pass
            return True
        
        # Clone
        repo_full = self._ensure_repo()
        self.local_clone.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            subprocess.run(
                ["git", "clone", f"git@github.com:{repo_full}.git", str(self.local_clone)],
                capture_output=True, text=True, timeout=60
            )
            return True
        except Exception:
            # If SSH fails, try HTTPS with token
            if self.token:
                try:
                    url = f"https://x-access-token:{self.token}@github.com/{repo_full}.git"
                    subprocess.run(
                        ["git", "clone", url, str(self.local_clone)],
                        capture_output=True, text=True, timeout=60
                    )
                    return True
                except:
                    pass
            return False
    
    def upload(self, local_path, remote_path):
        """Upload files to the repo and push."""
        local_path = Path(local_path)
        remote_path = str(remote_path).strip("/")
        
        if not self._ensure_clone():
            return False
        
        dest = self.local_clone / remote_path
        
        try:
            if local_path.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                for item in local_path.rglob('*'):
                    if item.is_file():
                        rel = item.relative_to(local_path)
                        file_dest = dest / rel
                        file_dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, file_dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, dest)
            
            # Git add, commit, push
            self._git_commit_and_push(f"Sync: {remote_path}")
            return True
        except Exception as e:
            print(f"Upload error: {e}")
            return False
    
    def download(self, remote_path, local_path):
        """Download files from the repo."""
        remote_path = str(remote_path).strip("/")
        
        if not self._ensure_clone():
            return False
        
        src = self.local_clone / remote_path
        local_path = Path(local_path)
        
        try:
            if src.is_dir():
                local_path.mkdir(parents=True, exist_ok=True)
                for item in src.rglob('*'):
                    if item.is_file():
                        rel = item.relative_to(src)
                        dest = local_path / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest)
            else:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, local_path)
            return True
        except Exception:
            return False
    
    def list_remote(self, remote_path):
        """List files in the repo."""
        remote_path = str(remote_path).strip("/")
        
        if not self._ensure_clone():
            return []
        
        src = self.local_clone / remote_path
        if src.exists():
            return [f.relative_to(src) for f in src.rglob('*') if f.is_file()]
        return []
    
    def delete_remote(self, remote_path):
        """Delete files from the repo."""
        remote_path = str(remote_path).strip("/")
        
        if not self._ensure_clone():
            return False
        
        target = self.local_clone / remote_path
        try:
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            
            self._git_commit_and_push(f"Delete: {remote_path}")
            return True
        except Exception:
            return False
    
    def get_status(self):
        """Get GitHub sync status."""
        repo = self.repo or self.repo_name or "not configured"
        return {
            "backend": "github",
            "repo": repo,
            "username": getattr(self, 'username', 'unknown'),
        }
    
    def _git_commit_and_push(self, message):
        """Stage, commit, and push changes."""
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.local_clone, capture_output=True, timeout=30
            )
            
            # Check if there are changes
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.local_clone, capture_output=True, text=True
            )
            
            if not status.stdout.strip():
                return  # Nothing to commit
            
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.local_clone, capture_output=True, timeout=30
            )
            
            subprocess.run(
                ["git", "push", "origin", "master"],
                cwd=self.local_clone, capture_output=True, timeout=60
            )
        except Exception as e:
            print(f"Git push error: {e}")
