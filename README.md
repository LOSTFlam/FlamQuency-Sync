# 🔥 FlamQuency-Sync

Terminal-based file synchronization with real version control, snapshots, and one-click rollback.

## Features

- **Full sync** — sync all your files, configs, and data with selective exclusion
- **Real version control** — content-addressable blob storage (SHA256) with per-file history
- **Full snapshots** — complete system state capture at sync points
- **One-button rollback** — restore entire system or specific files to any version
- **Cloud-ready** — GitHub auto-create & push, or local-only mode
- **Beautiful TUI** — Textual-based interface with arrow navigation
- **CLI mode** — run `flamquency sync` from terminal without TUI
- **Watch mode** — auto-sync on file changes
- **Compression** — zlib compression with deduplication
- **Diff** — compare text file versions

## Installation

```bash
# Clone
git clone https://github.com/LOSTFlam/FlamQuency-Sync.git
cd FlamQuency-Sync

# Install
pip install -e .

# Or with pip
pip install -r requirements.txt
```

## Usage

### TUI Mode (default)
```bash
flamquency-tui
# or
python -m flamquency.main
```

### CLI Mode
```bash
# Sync files
flamquency sync
flamquency sync --source ~/Documents

# Check status
flamquency status

# List snapshots
flamquency snapshots

# Rollback to snapshot
flamquency rollback --list
flamquency rollback --snapshot 0

# Per-file rollback
flamquency rollback-file ~/.config/hypr/hyprland.conf --list
flamquency rollback-file ~/.config/hypr/hyprland.conf --version 2

# Diff two versions
flamquency diff ~/.config/hypr/hyprland.conf --v1 0 --v2 2

# Watch mode (auto-sync)
flamquency watch ~/Documents ~/Pictures

# Config
flamquency config
flamquency config --edit
```

## Configuration

Config stored in `~/.flamquency/config.yaml`:

```yaml
cloud_backend: local  # local, github
cloud_repo_name: flamquency-sync-LOSTFlam
exclude_patterns:
  - "**/.flamquency/sync/**"
  - "**/.cache/**"
  - "**/*.tmp"
  - "**/__pycache__/**"
auto_sync: false
sync_interval_hours: 24
```

## GitHub Backend

Set `cloud_backend: github` in config. Requires `gh` CLI authenticated:

```bash
gh auth login --web --git-protocol ssh --scopes "repo"
```

The backend will:
1. Auto-create a private repo `flamquency-sync-<username>`
2. Clone it locally to `~/.flamquency/github-clone/`
3. Push snapshots and file versions on each sync

## Architecture

```
flamquency/
├── sync_engine.py       # Core sync engine
├── version_store.py     # Content-addressable blob storage
├── github_backend.py    # GitHub cloud backend
├── cloud.py             # Backend abstraction
├── config.py            # YAML configuration
├── textual_tui.py       # Textual TUI app
├── cli.py               # CLI commands
└── main.py              # Entry point
```

## Data Layout

```
~/.flamquency/
├── config.yaml          # User configuration
├── sync/                # Local sync destination
├── snapshots/           # System snapshots (manifests)
├── versions/
│   ├── blobs/           # Compressed file contents (SHA256)
│   └── files/           # Per-file version histories
└── github-clone/        # GitHub repo clone (if using GitHub backend)
```

## License

MIT
