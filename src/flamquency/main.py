"""Main entry point for FlamQuency-Sync."""
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flamquency.sync_engine import FlamQuencySync
from flamquency.config import load_config
from flamquency.cloud import get_backend, LOCAL
from flamquency.tui import run_tui

def main():
    """Main function."""
    # Load configuration
    config = load_config()
    
    # Set version in config if not present
    if "__version__" not in config:
        config["__version__"] = "0.1.0"
    
    # Initialize cloud backend
    backend_type = config.get("cloud_backend", "local")
    token = config.get("github_token")
    
    backend = get_backend(backend_type, 
                         repo_name=config.get("cloud_repo_name"),
                         token=token,
                         credentials_path=config.get("google_credentials"))
    
    # Authenticate backend
    if not backend.authenticate():
        print("Warning: Backend authentication may have issues")
    
    # Create sync engine
    sync = FlamQuencySync(config=config, backend=backend)
    
    # Show initial status
    status = sync.status()
    print(f"FlamQuency-Sync {status.get('__version__', '0.1.0')}")
    print(f"Backend: {status.get('backend', 'local')}")
    print(f"Last sync: {status.get('last_sync', 'Never')}")
    print()
    
    # Run TUI
    run_tui(sync)

if __name__ == "__main__":
    main()
