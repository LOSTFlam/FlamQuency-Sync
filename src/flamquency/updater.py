"""FlamQuency-Sync — автоматическая проверка и загрузка обновлений.

Источники версий (в порядке приоритета):
1. GitHub Releases API (когда релизы опубликованы).
2. Git tags в remote (`git ls-remote --tags`) — работает сразу,
   даже без релизов.

Поведение:
- Результат проверки кэшируется в ~/.flamquency/update-check.json
  на update_cache_hours (по умолчанию 6) — сеть не дёргается на каждый вызов.
- `flamquency update --check` — только проверить.
- `flamquency update` — показать и предложить обновиться.
- `flamquency update --yes` — обновиться автоматически (pip или git).

Обновление возможно, если:
- установка через pip (`pip install --upgrade flamquency-sync`), или
- клон репозитория (git pull в src-корне).
"""

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

REPO_URL = "https://github.com/LOSTFlam/FlamQuency-Sync"
API_URL = "https://api.github.com/repos/LOSTFlam/FlamQuency-Sync"
DEFAULT_CACHE_HOURS = 6
REQUEST_TIMEOUT = 8


@dataclass
class UpdateInfo:
    """Результат проверки обновлений."""
    available: bool = False
    current: str = "0.0.0"
    latest: str = "0.0.0"
    source: str = "none"           # github-release | git-tag | cache | error
    url: str = REPO_URL
    checked_at: str = ""
    error: str = ""
    release_notes: str = ""
    published_at: str = ""

    def to_dict(self):
        return {
            "available": self.available,
            "current": self.current,
            "latest": self.latest,
            "source": self.source,
            "url": self.url,
            "checked_at": self.checked_at,
            "error": self.error,
            "release_notes": self.release_notes,
            "published_at": self.published_at,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _version_tuple(version):
    """Версия → кортеж чисел для сравнения (1.2.3 → (1,2,3))."""
    import re
    parts = re.findall(r"\d+", version or "")
    return tuple(int(p) for p in parts[:4]) if parts else (0,)


def is_newer(latest, current):
    """latest строго новее current?"""
    a, b = _version_tuple(latest), _version_tuple(current)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


# ── Источники версий ────────────────────────────────────────

def _fetch_github_release():
    """Последний релиз через GitHub API. None если релизов нет/сеть легла."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{API_URL}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "flamquency-updater"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        tag = (data.get("tag_name") or "").lstrip("v")
        if not tag:
            return None
        return {
            "version": tag,
            "url": data.get("html_url") or REPO_URL,
            "notes": (data.get("body") or "")[:500],
            "published": data.get("published_at") or "",
            "source": "github-release",
        }
    except Exception:
        return None


def _fetch_git_tags():
    """Список тегов из remote через git ls-remote (без клонирования).

    Пробует origin, затем HTTPS-URL (работает без SSH-ключа).
    Возвращает None если репо недоступен; {"reachable": True, version: None}
    если репо доступен, но тегов ещё нет.
    """
    remotes = ["origin", f"{REPO_URL}.git"]
    for remote in remotes:
        try:
            out = subprocess.run(
                ["git", "ls-remote", "--tags", remote],
                capture_output=True, text=True, timeout=REQUEST_TIMEOUT,
            )
            if out.returncode != 0:
                continue
            tags = []
            for line in out.stdout.splitlines():
                ref = line.split("refs/tags/")[-1].strip() if "refs/tags/" in line else ""
                if ref and not ref.endswith("^{}"):
                    tags.append(ref.lstrip("v"))
            if not tags:
                return {"reachable": True, "version": None}
            latest = max(tags, key=_version_tuple)
            return {
                "version": latest,
                "url": f"{REPO_URL}/releases/tag/v{latest}",
                "notes": "",
                "published": "",
                "source": "git-tag",
            }
        except Exception:
            continue
    return None


# ── Кэш ─────────────────────────────────────────────────────

def _cache_path(base_dir):
    return Path(base_dir) / "update-check.json"


def _read_cache(base_dir, max_age_hours):
    path = _cache_path(base_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        checked = datetime.fromisoformat(data.get("checked_at", ""))
        if datetime.now() - checked > timedelta(hours=max_age_hours):
            return None
        return UpdateInfo.from_dict(data)
    except Exception:
        return None


def _write_cache(base_dir, info):
    path = _cache_path(base_dir)
    try:
        path.write_text(json.dumps(info.to_dict(), ensure_ascii=False, indent=2))
    except OSError:
        pass


# ── Публичный API ───────────────────────────────────────────

def check_for_update(current_version, base_dir=None, max_age_hours=None,
                     use_cache=True):
    """Проверить обновления. Возвращает UpdateInfo (never raises)."""
    base = Path(base_dir) if base_dir else Path.home() / ".flamquency"

    hours = max_age_hours
    if hours is None:
        try:
            from flamquency.config import load_config
            cfg = load_config()
            hours = (cfg.get("updates") or {}).get("cache_hours",
                                                   DEFAULT_CACHE_HOURS)
        except Exception:
            hours = DEFAULT_CACHE_HOURS

    info = UpdateInfo(current=current_version)
    info.checked_at = datetime.now().isoformat()

    # 1. Свежий кэш?
    if use_cache:
        cached = _read_cache(base, hours)
        if cached is not None and cached.checked_at:
            cached.current = current_version
            cached.available = is_newer(cached.latest, current_version)
            return cached

    # 2. GitHub Releases → git tags
    remote = _fetch_github_release() or _fetch_git_tags()
    if remote is None:
        # Оффлайн или приватный репо — сообщаем, но не падаем
        info.error = "не удалось связаться с GitHub (нет сети или репо приватный)"
        info.source = "error"
        return info

    if remote.get("version") is None:
        # Репо доступен, но релизов/тегов ещё нет
        info.latest = current_version
        info.source = remote.get("source", "none")
        info.error = "релизов ещё не опубликовано"
        info.available = False
        _write_cache(base, info)
        return info

    info.latest = remote["version"]
    info.url = remote["url"]
    info.release_notes = remote.get("notes", "")
    info.published_at = remote.get("published", "")
    info.source = remote["source"]
    info.available = is_newer(info.latest, info.current)

    _write_cache(base, info)
    return info


def detect_install_method():
    """Как установлена программа: pip | git | unknown.

    pip: рядом есть .dist-info / site-packages.
    git: src-корень — рабочий клон с .git.
    """
    pkg_dir = Path(__file__).resolve().parent
    # Git: ищем .git вверх по дереву от пакета
    for parent in [pkg_dir, *pkg_dir.parents]:
        if (parent / ".git").exists():
            return "git", parent
    # Pip: рядом с пакетом лежит dist-info (site-packages)
    site = pkg_dir.parent
    if site.name == "site-packages" or any(
        site.glob("flamquency_sync*.dist-info")
    ):
        return "pip", site
    return "unknown", pkg_dir


def perform_update(method=None, repo_dir=None, dry_run=False):
    """Обновиться. Возвращает (ok, сообщение).

    pip: pip install --upgrade git+REPO (для git-источника сборки).
    git: git fetch + git pull в клоне.
    """
    if method is None:
        method, detected_dir = detect_install_method()
        repo_dir = repo_dir or detected_dir

    if dry_run:
        return True, f"[dry-run] обновление через {method} в {repo_dir}"

    if method == "git":
        try:
            fetch = subprocess.run(
                ["git", "fetch", "--tags", "origin"],
                cwd=str(repo_dir), capture_output=True, text=True, timeout=60,
            )
            pull = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(repo_dir), capture_output=True, text=True, timeout=60,
            )
            if pull.returncode == 0:
                return True, "репозиторий обновлён (git pull --ff-only)"
            return False, f"git pull не удался:\n{pull.stderr.strip()[:300]}"
        except Exception as e:
            return False, f"git update failed: {e}"

    if method == "pip":
        try:
            out = subprocess.run(
                ["pip", "install", "--upgrade", f"git+{REPO_URL}.git"],
                capture_output=True, text=True, timeout=300,
            )
            if out.returncode == 0:
                return True, "пакет обновлён через pip"
            return False, f"pip install не удался:\n{out.stderr.strip()[:300]}"
        except FileNotFoundError:
            return False, "pip не найден — обновите вручную: pip install --upgrade git+" + REPO_URL
        except Exception as e:
            return False, f"pip update failed: {e}"

    return False, ("не удалось определить способ установки — "
                   f"обновите вручную: {REPO_URL}")
