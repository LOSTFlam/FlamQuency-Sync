# FlamQuency-Sync Design Document

## Vision
A beautiful, user-friendly terminal-based synchronization program that keeps ALL your files, configurations, and data in sync across devices with one-button rollback capabilities.

## Core Philosophy
- **Everything syncs** - by default everything is included, with selective exclusion
- **Granular control** - per-file versioning AND full system snapshots
- **One-button operations** - simple UI, powerful under the hood
- **Cloud-ready** - GitHub, Google Drive, or local storage
- **User-first** - designed for ordinary users, not just developers

## Key Features

### 1. Sync Engine
- **Selective inclusion** - exclude patterns (like .gitignore) for noise files
- **Two-way sync** - sync from source to destination and vice versa
- **Conflict resolution** - smart merge, ask user, or auto-resolve

### 2. Versioning System
- **Per-file git-style history** - each synced file gets git-like version tracking
- **Full system snapshots** - complete state capture at sync points
- **Dual rollback modes:**
  - Rollback entire system to previous sync point
  - Rollback specific files or folders to any previous version

### 3. Cloud Backend
- **GitHub integration** - auto-create repository, push sync state
- **Google Drive integration** - flexible upload/download with optional manual config
- **Local storage** - pure local sync without remote
- **Backend abstraction** - pluggable storage drivers

### 4. Terminal UI (TUI)
- **Beautiful design** with colors, borders, and clear layout
- **Main screen**: sync status, recent activity, quick actions
- **Sync panel**: select what to sync, exclude patterns
- **Rollback panel**: choose snapshot or file-specific rollback
- **Settings**: cloud config, exclusion patterns, UI preferences

### 5. Exclusion System
- Pattern-based exclusion (similar to .gitignore)
- Smart defaults exclude: caches, temp files, large binaries
- User-configurable include/exclude rules
- Preview before sync what will be affected

## Technical Architecture

### Language & Tools
- **Python 3.11+** - cross-platform, rich ecosystem
- **Textual** or **Rich** for TUI (beautiful terminal UI)
- **GitPython** - per-file versioning
- **Paramiko/Google APIs** - cloud storage
- **Fswatch/inotify** - file change detection

### Data Model
```
sync_state/
  .metadata/          # FlamQuency internal metadata
  snapshots/          # Full system snapshots (timestamped)
  versions/           # Per-file version history
  cloud/              # Remote storage state
  config.yaml         # User configuration (exclusions, cloud prefs)
```

### Sync Flow
1. **Scan** - scan source and destination directories
2. **Compare** - determine what changed since last sync
3. **Filter** - apply exclusion patterns
4. **Upload** - send changes to cloud (if enabled)
5. **Snapshot** - create full system snapshot
6. **Commit** - git-style per-file commits
7. **Update** - update metadata database

### Rollback Flow
1. **List** - show available snapshots or file versions
2. **Select** - user chooses which snapshot/file to rollback
3. **Execute** - restore files from chosen state
4. **Update** - update metadata, create new snapshot if desired

## Cloud Backend Design

### GitHub Mode
- Auto-create repository `flamquency-sync-<username>`
- Push snapshot metadata and version trees
- Raw file storage in `snapshots/` and `versions/` directories
- Issues for conflict tracking (optional)

### Google Drive Mode
- OAuth2 flow for authentication
- Folder structure: `FlamQuencySync/<username>/`
- Upload/download with progress tracking
- Manual folder selection on first run

### Local Mode
- Store everything in `~/.flamquency/sync/`
- No remote dependencies
- Good for single-device setups or LAN sync

## UI Design (TUI)

### Main Layout
```
+========================================+
|       FlamQuency-Sync v0.1.0           |
+----------------------------------------+
|  [1] Sync Now              [2] Rollback  |
|  [3] Settings              [4] About   |
+----------------------------------------+
|  Current Status: Synced at 14:32:05    |
|  Last sync: 2 hours ago | 12,450 files |
+========================================+
```

### Sync Panel
```
+----------------------------------------+
|  What do you want to sync?             |
|  [ ] /home/user/.config                |
|  [ ] /home/user/Documents              |
|  [ ] /home/user/Pictures               |
|  [ ] /home/user/Movies                 |
|  [ ] Custom paths                      |
|                                        |
|  Exclude patterns:                     |
|  [ ] **/*.cache                        |
|  [ ] **/*.tmp                          |
|  [ ] **/CheatEngine*.exe               |
+----------------------------------------+
```

### Rollback Panel
```
+----------------------------------------+
|  Rollback to previous state?           |
|                                        |
|  [A] Full system snapshots:            |
|      • 2026-10-12 14:32:05 (latest)    |
|      • 2026-10-12 10:15:22            |
|      • 2026-10-11 22:40:11            |
|                                        |
|  [B] Per-file versions:                |
|      • config.json → v3 → v2 → v1      |
|      • .bashrc → v15 → v14 → ...     |
|      • themes/awesome.lua → v8 → ...  |
+----------------------------------------+
```

## Non-Goals (for MVP)
- Windows GUI (terminal-only TUI for now)
- Real-time live sync (sync on-demand or scheduled)
- Web interface (TUI only, may add later)
- AI-powered conflict resolution (manual user choice)

## Roadmap
- **v0.1**: Core sync engine, TUI, git-style per-file versioning, local-only mode
- **v0.2**: GitHub integration, Google Drive, exclusion patterns
- **v0.3**: Full rollback system, snapshot management
- **v1.0**: Windows support, web dashboard, plugin system