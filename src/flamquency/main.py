"""Main entry point for FlamQuency-Sync."""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flamquency.sync_engine import FlamQuencySync
from flamquency.config import load_config
from flamquency.cloud import get_backend, LocalBackend


def main():
    """Launch the Textual TUI."""
    config = load_config()
    
    if "__version__" not in config:
        config["__version__"] = "0.1.0"
    
    backend_type = config.get("cloud_backend", "local")
    if backend_type == "local":
        backend = LocalBackend()
    elif backend_type == "github":
        backend = get_backend("github",
                             repo_name=config.get("cloud_repo_name"),
                             token=config.get("github_token"))
    else:
        backend = LocalBackend()
    
    if not backend.authenticate():
        print("Warning: Backend authentication may have issues")
    
    sync = FlamQuencySync(config=config, backend=backend)
    
    # Use Textual TUI
    from flamquency.textual_tui import run_textual_tui
    run_textual_tui(sync)


if __name__ == "__main__":
    main()
