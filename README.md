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
- **Encryption** — optional Fernet (AES-128) encryption of stored blobs with your password
- **.flamquencyignore** — gitignore-style rules so you decide exactly what never gets synced

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

# Encryption (blob store at rest)
flamquency encryption status
flamquency encryption enable            # asks for a password interactively
flamquency encryption disable
flamquency encryption change-password

# Ignore rules (~/.flamquencyignore)
flamquency ignore --init                # create the starter ignore file
flamquency ignore --list                # show the loaded rules
flamquency ignore --add "*.psd"         # append a pattern
flamquency ignore --check design.psd    # explain whether a path is ignored
```

The password can also come from the `FLAMQUENCY_PASSWORD` environment
variable or the `--password/-p` flag, which is handy for scripts:

```bash
FLAMQUENCY_PASSWORD='my secret' flamquency sync --source ~/Documents
```

## Encryption

Blobs (the actual file contents in `~/.flamquency/versions/blobs/`) can be
encrypted at rest with Fernet — AES-128-CBC with HMAC-SHA256 authentication.

- **Key derivation**: PBKDF2-HMAC-SHA256, 480 000 iterations, random 16-byte salt
- **Key file**: `~/.flamquency/versions/encryption.json` (mode `0600`) — stores
  only the salt, iteration count and a verifier token. The password itself and
  the derived key are never written to disk
- **Per-blob flag**: the blob index records whether each blob is encrypted, so
  a store that was plaintext before encryption keeps working, and disabling
  encryption decrypts existing blobs in place
- **Locked store**: while locked, sync and snapshots refuse to run instead of
  silently writing plaintext — you always know your data is protected
- **Password change**: re-encrypts every existing blob under the new key

```bash
# Enable, then sync as usual
flamquency encryption enable
flamquency sync

# Later runs need the password (flag, env var, or interactive prompt)
flamquency sync --password 'my secret'

# Rotate the password (re-encrypts all blobs)
flamquency encryption change-password --new-password 'new secret'

# Turn it off (decrypts everything in place)
flamquency encryption disable
```

> ⚠️ Without the password the encrypted blobs are unrecoverable — there is no
> backdoor. Keep a backup of `~/.flamquency/` somewhere safe.

## .flamquencyignore

`~/.flamquencyignore` lets you decide exactly what never gets synced — the
syntax is the familiar `.gitignore` one, so there is nothing new to learn:

```gitignore
# comments start with #
*.log              # ignore every .log at any depth
!keep.log          # negation — re-include (last matching rule wins)
build/             # directories only (trailing slash)
/rooted.txt        # anchored to the home directory
**/node_modules    # ** crosses directory boundaries
temp?.tmp          # ? matches exactly one character
```

- **Last match wins** — rules are evaluated in order; a `!` rule re-includes
  what an earlier rule excluded
- **Ignored directories are pruned** — nothing inside them is ever walked,
  which also keeps large trees fast
- **Your rules override the built-in defaults** — the default config excludes
  `*.log`, but `!keep.log` brings it back. Internal FlamQuency data
  (`~/.flamquency/versions/**`, the encryption key file, …) stays protected
  no matter what you write — those are hard excludes
- **No file, no problem** — a missing `.flamquencyignore` simply means no
  extra rules; sync behaves exactly as before

```bash
flamquency ignore --init              # write the starter file
flamquency ignore --list              # show rules with their flags
flamquency ignore --add "*.psd"       # append a pattern
flamquency ignore --check design.psd  # which rule decides for this path?
```

`flamquency status` reports the active file and rule count. Disable the whole
mechanism with `use_ignore_file: false` in the config, or point it elsewhere
with `ignore_file_path: /path/to/file`.

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
├── encryption.py        # Fernet/AES blob encryption
├── ignore.py            # .flamquencyignore (gitignore-style rules)
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
│   ├── files/           # Per-file version histories
│   └── encryption.json  # Encryption key file (only when enabled)
└── github-clone/        # GitHub repo clone (if using GitHub backend)
```

## License

MIT
