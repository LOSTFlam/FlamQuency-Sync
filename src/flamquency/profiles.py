"""Sync profiles — named sets of paths for different sync scenarios.

A profile is a named bundle of source paths (plus optional extra exclude
patterns and a description) stored inside the config file:

    profiles:
      default:
        paths: ["~/.flamquency"]
        exclude_patterns: []
        description: "Home FlamQuency directory"
      work:
        paths: ["~/projects/work", "~/Documents/notes"]
        exclude_patterns: ["*.secret"]
        description: "Work files only"
    active_profile: default

`flamquency sync` follows the *active* profile; `--profile NAME` runs a
different one for a single pass without switching. An explicit
`--source PATH` still bypasses profiles entirely (single-root, old
behaviour), so nothing that worked before changes.
"""

import copy
from pathlib import Path

DEFAULT_PROFILE_NAME = "default"


class ProfileError(Exception):
    """Any invalid profile operation (unknown name, bad path, ...)."""


# ── validation ────────────────────────────────────────────────

def _validate_name(name):
    """Profile names must be non-empty, single-line and path-segment safe."""
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("Profile name must not be empty")
    name = name.strip()
    if "/" in name or "\\" in name or name in (".", ".."):
        raise ProfileError(f"Invalid profile name: {name!r}")
    return name


def _validate_paths(paths):
    """A profile keeps at least one path; duplicates are collapsed."""
    if not paths:
        raise ProfileError("A profile needs at least one path")
    normalized = []
    for p in paths:
        if p is None or not str(p).strip():
            raise ProfileError("Profile path must not be empty")
        expanded = str(Path(str(p).strip()).expanduser())
        if expanded not in normalized:
            normalized.append(expanded)
    if not normalized:
        raise ProfileError("A profile needs at least one path")
    return normalized


# ── structure ─────────────────────────────────────────────────

def ensure_profiles(config):
    """Guarantee the config carries a profiles section + an active profile.

    Older configs (written before profiles existed) get the structural
    `default` profile pointing at ~/.flamquency — the historical sync
    root — so upgrading is seamless.
    """
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        profiles = {DEFAULT_PROFILE_NAME: default_profile()}
        config["profiles"] = profiles
    if DEFAULT_PROFILE_NAME not in profiles:
        profiles[DEFAULT_PROFILE_NAME] = default_profile()
    if not config.get("active_profile"):
        config["active_profile"] = DEFAULT_PROFILE_NAME
    return config


def default_profile():
    """The built-in default profile: the historical ~/.flamquency root."""
    return {
        "paths": [str(Path.home() / ".flamquency")],
        "exclude_patterns": [],
        "description": "Home FlamQuency directory",
    }


def _profile_dict(name, paths, description="", exclude_patterns=None):
    return {
        "paths": _validate_paths(paths),
        "exclude_patterns": list(exclude_patterns or []),
        "description": description or "",
    }


# ── queries ───────────────────────────────────────────────────

def profile_names(config):
    """Sorted profile names (stable output for listings)."""
    ensure_profiles(config)
    return sorted(config["profiles"])


def get_profile(config, name):
    """The profile dict for `name` — raises ProfileError when unknown."""
    ensure_profiles(config)
    name = _validate_name(name)
    profiles = config["profiles"]
    if name not in profiles:
        known = ", ".join(sorted(profiles))
        raise ProfileError(f"Unknown profile: {name!r} (have: {known})")
    return profiles[name]


def active_name(config):
    """Active profile name, healing a dangling reference back to default."""
    ensure_profiles(config)
    name = config.get("active_profile") or DEFAULT_PROFILE_NAME
    if name not in config["profiles"]:
        config["active_profile"] = DEFAULT_PROFILE_NAME
        return DEFAULT_PROFILE_NAME
    return name


def active_profile(config):
    """The active profile's dict."""
    return get_profile(config, active_name(config))


def profile_paths(config, name):
    """Expanded, deduplicated Path objects of a profile."""
    return [Path(p) for p in get_profile(config, name)["paths"]]


def exclude_patterns(config, profile):
    """Config defaults + this profile's extra patterns (deduped, ordered)."""
    merged = list(config.get("exclude_patterns", []))
    for pattern in profile.get("exclude_patterns", []):
        if pattern not in merged:
            merged.append(pattern)
    return merged


# ── mutations ─────────────────────────────────────────────────

def create_profile(config, name, paths, description="", exclude_patterns=None):
    """Add a new profile. Refuses duplicates and empty path lists."""
    ensure_profiles(config)
    name = _validate_name(name)
    if name in config["profiles"]:
        raise ProfileError(f"Profile already exists: {name!r}")
    profile = _profile_dict(name, paths, description, exclude_patterns)
    config["profiles"][name] = profile
    return profile


def delete_profile(config, name):
    """Remove a profile. The default profile and the active one are protected."""
    ensure_profiles(config)
    name = _validate_name(name)
    if name == DEFAULT_PROFILE_NAME:
        raise ProfileError("The 'default' profile cannot be deleted")
    if name not in config["profiles"]:
        raise ProfileError(f"Unknown profile: {name!r}")
    if active_name(config) == name:
        raise ProfileError(
            f"Profile {name!r} is active — switch first "
            f"(flamquency profile use default)"
        )
    del config["profiles"][name]


def add_path(config, name, path):
    """Append one path to a profile (idempotent)."""
    profile = get_profile(config, name)
    expanded = str(Path(str(path).strip()).expanduser())
    if expanded not in profile["paths"]:
        profile["paths"].append(expanded)
    return profile["paths"]


def remove_path(config, name, path):
    """Drop one path from a profile — the last one may not be removed."""
    profile = get_profile(config, name)
    expanded = str(Path(str(path).strip()).expanduser())
    if expanded not in profile["paths"]:
        raise ProfileError(f"Path not in profile {name!r}: {path}")
    if len(profile["paths"]) == 1:
        raise ProfileError(
            f"Profile {name!r} must keep at least one path — delete the profile instead"
        )
    profile["paths"].remove(expanded)
    return profile["paths"]


def set_active(config, name):
    """Make `name` the active profile."""
    get_profile(config, name)  # validates
    config["active_profile"] = name
    return name


def set_description(config, name, description):
    """Update a profile's description."""
    profile = get_profile(config, name)
    profile["description"] = description or ""
    return profile


def deep_copy_defaults(config):
    """Deep copy so DEFAULT_CONFIG's nested dicts/lists are never shared."""
    return copy.deepcopy(config)
