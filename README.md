# FlamQuency-Sync

Terminal-based file synchronization with full rollback capabilities.

## Features

- **Full sync**: Sync all your files, configurations, and data
- **Selective exclusion**: Exclude patterns for noise files (caches, temps, etc.)
- **Per-file versioning**: Git-style version history for individual files
- **Full snapshots**: Complete system snapshots at sync points
- **One-button rollback**: Rollback entire system or specific files
- **Cloud-ready**: GitHub, Google Drive, or local storage
- **Beautiful TUI**: Rich terminal interface with nice design

## Installation

```bash
# Clone the repository
git clone https://github.com/LOSTFlam/FlamQuency-Sync.git
cd FlamQuency-Sync

# Install
pip install -e .

# Or install dependencies manually
pip install rich
```

## Usage

```bash
# Start the TUI
flamquency

# Or run directly
python -m flamquency.main
```

## Configuration

Configuration is stored in `~/.flamquency/config.yaml`. Edit it to:
- Change cloud backend (local, github, google_drive)
- Add/remove exclusion patterns
- Set auto-sync preferences

## Cloud Backends

### Local (default)
All data stored in `~/.flamquency/sync/`

### GitHub
Requires GitHub token. Creates a private repo for sync state.

### Google Drive
OAuth2 flow for authentication.

## License

MIT
