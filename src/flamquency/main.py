"""Main entry point for FlamQuency-Sync."""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flamquency.sync_engine import FlamQuencySync
from flamquency.config import load_config
from flamquency.cloud import get_backend, LocalBackend
from flamquency.tui import run_tui

def main():
    config = load_config()
    
    if "__version__" not in config:
        config["__version__"] = "0.1.0"
    
    backend_type = config.get("cloud_backend", "local")
    if backend_type == "local":
        backend = LocalBackend()
    else:
        backend = get_backend(backend_type,
                             repo_name=config.get("cloud_repo_name"),
                             token=config.get("github_token"),
                             credentials_path=config.get("google_credentials"))
    
    if not backend.authenticate():
        print("Warning: Backend authentication may have issues")
    
    sync = FlamQuencySync(config=config, backend=backend)
    run_tui(sync)

if __name__ == "__main__":
    main()
