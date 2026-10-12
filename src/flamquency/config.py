"""Configuration management for FlamQuency-Sync."""
import os
import yaml
from pathlib import Path

# Base directories
XDG_HOME = Path.home() / ".flamquency"
CONFIG_PATH = XDG_HOME / "config.yaml"
DATA_PATH = XDG_HOME / "data"

# Default configuration
DEFAULT_CONFIG = {
    "cloud_backend": "local",  # local, github, google_drive
    "cloud_repo_name": "flamquency-sync-{username}",
    "exclude_patterns": [
        # Internal FlamQuency directories (prevent recursion)
        "**/.flamquency/sync/**",
        "**/.flamquency/snapshots/**",
        "**/.flamquency/versions/**",
        "**/.flamquency/data/**",
        "**/.flamquency/encryption.json",  # never sync the encryption key file
        # Common noise
        "**/.cache/**",
        "**/*.tmp",
        "**/CheatEngine*.exe",
        "**/CheatEngineLinux*.exe",
        "**/*.log",
        "**/__pycache__/**",
        "**/.git/**",
    ],
    "auto_sync": False,
    "sync_interval_hours": 24,
    "last_sync": None,
    "use_ignore_file": True,  # honor ~/.flamquencyignore (gitignore-style)
    "ignore_file_path": None,  # custom path; None = ~/.flamquencyignore
    "encryption": {
        "enabled": False,  # Fernet/AES encryption of stored blobs
    },
    "ui": {
        "theme": "default",
        "color_accent": "cyan",
        "show_file_counts": True,
    },
}

def load_config():
    """Load configuration from disk, merging with defaults."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                user_config = yaml.safe_load(f)
        except:
            user_config = {}
        # Handle None from empty/special yaml files
        if user_config is None:
            user_config = {}
        # Merge with defaults
        config = merge_configs(DEFAULT_CONFIG, user_config)
    else:
        config = DEFAULT_CONFIG.copy()
        save_config(config)
    return config

def save_config(config, config_path=None):
    """Save configuration to disk."""
    if config_path is None:
        config_path = CONFIG_PATH
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

def merge_configs(default, user):
    """Recursively merge user config into defaults."""
    result = default.copy()
    for key, value in user.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result

def get_exclude_patterns(config):
    """Get the list of exclusion patterns from config."""
    return config.get("exclude_patterns", DEFAULT_CONFIG["exclude_patterns"])
