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
- **Sync profiles** — named sets of paths for different scenarios, switchable in one command
- **Retention policy** — restic-style pruning: keep-last / hourly / daily / weekly / monthly / yearly / keep-within
- **Integrity check** — `flamquency check` verifies the blob store (restic-check analogue)
- **Storage stats** — `flamquency stats`: dedup ratio, saved space, encryption,
  per-type bar chart, top-changed files, and `--graphs` for the storage
  growth sparkline plus a snapshot timeline
- **Backends** — `flamquency backend`: local, GitHub, S3 (AWS/MinIO/B2/Wasabi),
  SMB/NFS shares, Google Drive and Dropbox via rclone; secrets stay in env vars
- **Scheduling** — `flamquency schedule "каждый час"`: cron (Linux/macOS) or
  Task Scheduler (Windows), smart autosync with a quiet period, post-sync hooks
- **Evolution** — `flamquency evolve`: learns which files you edit most and
  suggests profiles, priorities and shortcuts
- **Content versioning** — `restore-content` / `view-content` / `restore-tree`:
  read or restore any version anywhere, whole directories at once, and a
  colour-coded `diff`
- **Ignore by size and type** — `ignore --size-gt 1GB --types mp4,avi`; glob
  rules answer *which*, size/type rules answer *how big* and *what kind*
- **Spark** — `spark`: your own quick actions, one command each, three built in
- **Memory echo** — `echo`: reads your shell history and suggests paths to sync
- **Kaleidoscope** — `kaleido`: colour variations of the «Угольки» theme, same
  readability, different character
- **Rich help** — `help`: what a command is *for*, live examples, and links to
  related commands; completions are generated from the CLI itself for bash,
  zsh and fish
- **Auto-update** — `flamquency update`: checks GitHub releases/git-tags, installs via pip or git
- **Nerd Font icons** — no emoji; automatic ASCII fallback when the font is missing
- **«Угольки» design system** — one palette for CLI and TUI, see docs/DESIGN.md

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

# Quick setup (creates config, ignore file, retention policy)
flamquency init --keep-last 10

# Prune old snapshots (restic-style retention)
flamquency prune --keep-last 5 --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --dry-run
flamquency prune --older-than 30 --yes
flamquency prune --keep-within 1y6m --yes

# Integrity check (restic-check analogue)
flamquency check

# Storage statistics (dedup, saved space)
flamquency stats

# Updates
flamquency update --check     # only check
flamquency update             # check + install (asks)
flamquency update --yes       # check + install automatically

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

### Ignore by size and type

Glob rules answer *which* files; sometimes you want *how big* or *what kind*.
Global rules answer that, and they live in the config so they apply even with
the ignore file disabled:

```bash
flamquency ignore --size-gt 1GB       # skip anything over a gigabyte
flamquency ignore --size-lt 10KB      # skip specks smaller than metadata
flamquency ignore --types mp4,avi     # skip video by extension
flamquency ignore --clear-global      # drop all size/type rules
```

The same syntax works inside the ignore file itself:

```gitignore
size>1GB          # files larger than 1 GiB
size<=10KB        # tiny files not worth versioning
type=mp4,avi,mkv  # by extension, case-insensitive
```

Size rules apply **after** the file rules, so a `!important.mkv` still wins
over `type=mkv`. `flamquency ignore --check` prints exactly which rule
decided — including its size, when the file is on disk.

`flamquency status` reports the active file and rule count. Disable the whole
mechanism with `use_ignore_file: false` in the config, or point it elsewhere
with `ignore_file_path: /path/to/file`.

## Sync profiles

One install, several scenarios. A **profile** is a named set of paths (plus
optional extra excludes and a description). `flamquency sync` follows the
*active* profile — no more one-giant-tree syncs when you only meant to back
up your documents.

```bash
# Create a profile with several paths at once
flamquency profile create work \
    --path ~/projects/work \
    --path ~/Documents \
    --description "Work files" \
    --exclude "*.secret"

flamquency profile use work        # make it the active one
flamquency sync                    # syncs every path of the active profile

flamquency profile add-path work ~/notes     # grow it later
flamquency profile remove-path work ~/notes  # shrink it back
flamquency profile list             # → shows every profile and the active one
flamquency profile show work        # one profile in detail
flamquency profile delete old       # remove one (active/default are protected)

# One-off run of another profile — the active profile stays untouched
flamquency sync --profile media

# An explicit source still bypasses profiles entirely (classic single-root sync)
flamquency sync --source ~/some/dir
```

How a profile sync behaves:

- **Each path is synced in turn** into `~/.flamquency/sync/<label>/`, where
  the label is the path's basename — two roots with identically named files
  never clobber each other
- **Version histories are keyed per root** (`docs/todo.md` vs
  `code/todo.md`), so per-file rollback stays exact
- **One snapshot per synced path**, named after the root — rollbacks stay
  readable
- **Missing paths are reported, never silently skipped** — the error list
  in the sync summary names them
- **Profile excludes stack on top of the config defaults** — `*.secret` from
  the profile and `*.log` from the config both apply
- **`default` is structural** — it points at `~/.flamquency` (the historical
  sync root), so an upgraded config keeps working with zero changes; it
  cannot be deleted, and neither can the profile you're currently using

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
├── profiles.py          # Sync profiles (named sets of paths)
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
