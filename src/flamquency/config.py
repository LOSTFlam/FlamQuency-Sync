"""Configuration management for FlamQuency-Sync."""
import copy
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
    # ── Планирование и автоматизация (v2.0) ──────────────────
    "schedule": None,          # cron-строка или None — расписание выключено
    "schedule_profile": None,  # профиль, который синкается по расписанию
    "smart_autosync": True,    # умный таймаут вместо фиксированного дебаунса
    "smart_autosync_timeout": 5,   # секунд тишины перед синком
    "post_sync_script": None,  # путь к скрипту после успешного синка
    # ── «Эволюция»: самообучение на привычках ────────────────
    "evolution": {
        "enabled": True,
        "learning_rate": 0.3,       # 0..1 — вес новых наблюдений
        "hot_file_threshold": 2,    # сколько правок делает файл «горячим»
        "auto_ignore_learned": False,  # предлагать игнор по наблюдениям
        "tracked_commands": {},     # команда → сколько раз запускали
        "file_heat": {},            # rel_path → счётчик изменений
        "learned_excludes": [],     # паттерны, которые эволюция предложила
    },
    "use_ignore_file": True,  # honor ~/.flamquencyignore (gitignore-style)
    "ignore_file_path": None,  # custom path; None = ~/.flamquencyignore
    "active_profile": "default",  # which sync profile `flamquency sync` follows
    "profiles": {},  # named sets of paths — filled by ensure_profiles()
    "encryption": {
        "enabled": False,  # Fernet/AES encryption of stored blobs
    },
    "ui": {
        "theme": "default",
        "color_accent": "cyan",
        "show_file_counts": True,
    },
}

def load_config(config_path=None):
    """Load configuration from disk, merging with defaults.

    The result is always a deep copy of the defaults: mutating one loaded
    config (e.g. adding a profile) must never leak into the next load.
    """
    if config_path is None:
        config_path = CONFIG_PATH
    config_path = Path(config_path)
    if config_path.exists():
        try:
            with open(config_path) as f:
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
        save_config(config, config_path=config_path)
    # Deep-copy the defaults so callers can freely mutate the result
    # without corrupting DEFAULT_CONFIG for the next load.
    config = copy.deepcopy(config)
    # A loaded config always carries a usable profiles section.
    from flamquency.profiles import ensure_profiles
    ensure_profiles(config)
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
