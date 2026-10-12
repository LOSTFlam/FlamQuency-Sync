"""Реестр бэкендов FlamQuency-Sync v2.0 — S3 и сетевые хранилища.

Модуль решает три задачи:

1. **Каталог** (:data:`BACKENDS`) — что вообще поддерживается, какие у
   бэкенда настройки и в каких переменных окружения лежат секреты.
2. **Диагностика** (:func:`describe_backend`) — почему бэкенд не готов:
   нет библиотеки, нет переменной окружения, не заполнена настройка.
3. **Создание** (:func:`create_backend`) — фабрика, которая честно падает
   с понятной ошибкой, если чего-то не хватает, вместо «молчаливого»
   отката на LocalBackend.

Главное правило безопасности: **секреты не хранятся в config.yaml**.
В конфиге живёт только имя переменной окружения, из которой бэкенд читает
ключ в момент работы. Так конфиг можно смело коммитить и синкарить.

Сетевые бэкенды (SMB/NFS) монтируются не нами: пользователь монтирует сам
(или через systemd), а FlamQuency работает с готовой точкой монтирования —
так же, как с локальной папкой. Мы только проверяем, что она есть.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from flamquency.cloud import CloudBackend, LocalBackend


class BackendError(Exception):
    """Бэкенд не готов: нет библиотеки, секрета или настройки."""


# ── каталог бэкендов ──────────────────────────────────────────

BACKENDS = {
    "local": {
        "title": "Локальная папка",
        "kind": "local",
        "description": "Хранилище на этом же диске (~/.flamquency/sync).",
        "settings": [],
        "secrets": [],
        "requires_mount": False,
        "platforms": ["linux", "macos", "windows"],
    },
    "github": {
        "title": "GitHub",
        "kind": "git",
        "description": "Приватный репозиторий как хранилище (Git CLI).",
        "settings": ["cloud_repo_name"],
        "secrets": ["token"],
        "secret_envs": {"token": "FLAMQUENCY_GITHUB_TOKEN"},
        "requires_mount": False,
        "platforms": ["linux", "macos", "windows"],
    },
    "s3": {
        "title": "S3-совместимое хранилище",
        "kind": "s3",
        "description": "AWS S3, MinIO, Backblaze B2, Wasabi и другие S3 API.",
        "settings": ["bucket", "endpoint", "region", "prefix"],
        "secrets": ["access_key", "secret_key"],
        "secret_envs": {"access_key": "FLAMQUENCY_S3_ACCESS_KEY",
                        "secret_key": "FLAMQUENCY_S3_SECRET_KEY"},
        "requires_mount": False,
        "platforms": ["linux", "macos", "windows"],
        "library": "boto3",
    },
    "smb": {
        "title": "SMB / CIFS share",
        "kind": "network",
        "description": "Сетевая Windows-папка. Нужна смонтированная точка.",
        "settings": ["server", "mount_point"],
        "secrets": ["username", "password"],
        "secret_envs": {"username": "FLAMQUENCY_SMB_USER",
                        "password": "FLAMQUENCY_SMB_PASSWORD"},
        "requires_mount": True,
        "platforms": ["linux", "macos", "windows"],
    },
    "nfs": {
        "title": "NFS export",
        "kind": "network",
        "description": "Сетевая NFS-папка. Нужна смонтированная точка.",
        "settings": ["server", "mount_point"],
        "secrets": [],
        "requires_mount": True,
        "platforms": ["linux", "macos"],
    },
    "gdrive": {
        "title": "Google Drive",
        "kind": "cloud",
        "description": "Папка в Google Drive (токен доступа).",
        "settings": ["folder_id"],
        "secrets": ["token"],
        "secret_envs": {"token": "FLAMQUENCY_GDRIVE_TOKEN"},
        "requires_mount": False,
        "platforms": ["linux", "macos", "windows"],
    },
    "dropbox": {
        "title": "Dropbox",
        "kind": "cloud",
        "description": "Папка в Dropbox (токен доступа).",
        "settings": ["path"],
        "secrets": ["token"],
        "secret_envs": {"token": "FLAMQUENCY_DROPBOX_TOKEN"},
        "requires_mount": False,
        "platforms": ["linux", "macos", "windows"],
    },
}


def backend_names():
    """Отсортированные имена поддерживаемых бэкендов."""
    return sorted(BACKENDS)


def _current_platform():
    import sys
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


# ── диагностика ───────────────────────────────────────────────

def _secret_env(config, backend, secret):
    """Имя переменной окружения для секрета.

    Приоритет: что указано в конфиге пользователя → каноничное имя из
    каталога бэкендов. Явная пустая строка (``password_env: ""``) означает
    «секрет не нужен» — так настраиваются гостевые шары и одноранговые
    NFS, и диагностика не должна требовать невозможного.
    """
    settings = config.get("backends", {}).get(backend, {}) or {}
    if f"{secret}_env" in settings:
        return settings[f"{secret}_env"] or None
    canonical = BACKENDS.get(backend, {}).get("secret_envs", {})
    return canonical.get(secret)


def _library_available(name):
    if not name:
        return True
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def describe_backend(config, name):
    """Готовность бэкенда: (ok, список проблем, человекое описание).

    Проблемы — короткие строки, пригодные и для CLI, и для TUI.
    """
    problems = []
    if name not in BACKENDS:
        return False, [f"Неизвестный бэкенд: {name!r}"], ""
    spec = BACKENDS[name]

    if _current_platform() not in spec["platforms"]:
        problems.append(
            f"Не поддерживается на {_current_platform()} "
            f"(только: {', '.join(spec['platforms'])})")

    library = spec.get("library")
    if library and not _library_available(library):
        problems.append(f"Нужна библиотека: pip install {library}")

    settings = config.get("backends", {}).get(name, {}) or {}
    for key in spec["settings"]:
        if not settings.get(key):
            problems.append(f"Не задана настройка: backends.{name}.{key}")

    for secret in spec["secrets"]:
        env_name = _secret_env(config, name, secret)
        if env_name and not os.environ.get(env_name):
            problems.append(f"Нет переменной окружения: {env_name}")

    if spec["requires_mount"]:
        mount = settings.get("mount_point")
        if mount and not Path(mount).expanduser().is_dir():
            problems.append(f"Точка монтирования недоступна: {mount}")

    return (not problems), problems, spec["description"]


# ── бэкенды ───────────────────────────────────────────────────

class NetworkBackend(CloudBackend):
    """Бэкенд над уже смонтированной сетевой папкой (SMB/NFS).

    Работает как LocalBackend, но честно сообщает свою природу и
    проверяет доступность точки монтирования при инициализации.
    """

    kind = "network"

    def __init__(self, base_path, name, mount_point):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.mount_point = Path(mount_point)
        self.error = None

    def authenticate(self) -> bool:
        if not self.mount_point.is_dir():
            self.error = f"Не смонтировано: {self.mount_point}"
            return False
        return True

    def upload(self, local_path, remote_path) -> bool:
        remote = self.base_path / remote_path
        if local_path.is_dir():
            remote.mkdir(parents=True, exist_ok=True)
            for item in local_path.rglob("*"):
                if item.is_file():
                    dest = remote / item.relative_to(local_path)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(item.read_bytes())
        else:
            remote.parent.mkdir(parents=True, exist_ok=True)
            remote.write_bytes(local_path.read_bytes())
        return True

    def download(self, remote_path, local_path) -> bool:
        remote = self.base_path / remote_path
        if remote.is_dir():
            local_path.mkdir(parents=True, exist_ok=True)
            for item in remote.rglob("*"):
                if item.is_file():
                    dest = local_path / item.relative_to(remote)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(item.read_bytes())
        elif remote.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(remote.read_bytes())
            return True
        return False

    def list_remote(self, remote_path):
        remote = self.base_path / remote_path
        if remote.exists():
            return [f.relative_to(remote) for f in remote.rglob("*")
                    if f.is_file()]
        return []

    def delete_remote(self, remote_path) -> bool:
        remote = self.base_path / remote_path
        if not remote.exists():
            return False
        if remote.is_file():
            remote.unlink()
        else:
            for item in remote.rglob("*"):
                if item.is_file():
                    item.unlink()
        return True

    def get_status(self):
        return {
            "backend": self.name,
            "base_path": str(self.base_path),
            "mount_point": str(self.mount_point),
            "mounted": self.mount_point.is_dir(),
            "error": self.error,
            "synced_items": len(list(self.base_path.rglob("*")))
            if self.base_path.exists() else 0,
        }


class S3Backend(CloudBackend):
    """S3-совместимое хранилище (AWS S3, MinIO, B2, Wasabi).

    Требует boto3. Секреты берутся из переменных окружения, названных в
    конфиге, — в самом конфиге ключей нет.
    """

    kind = "s3"

    def __init__(self, settings, base_path):
        try:
            import boto3                                   # noqa: F401
        except ImportError as e:
            raise BackendError(
                "S3-бэкенд требует boto3: pip install boto3") from e
        self.settings = settings
        self.base_path = Path(base_path)                   # локальный кэш
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.bucket = settings.get("bucket", "")
        self.prefix = settings.get("prefix", "").lstrip("/")
        self._client = None

    # — подключение —

    def _credentials(self):
        access = os.environ.get(
            self.settings.get("access_key_env") or "", "")
        secret = os.environ.get(
            self.settings.get("secret_key_env") or "", "")
        return access or None, secret or None

    def _connect(self):
        if self._client is not None:
            return self._client
        import boto3
        access, secret = self._credentials()
        self._client = boto3.client(
            "s3",
            endpoint_url=self.settings.get("endpoint") or None,
            region_name=self.settings.get("region") or None,
            aws_access_key_id=access,
            aws_secret_access_key=secret,
        )
        return self._client

    def authenticate(self) -> bool:
        try:
            self._connect().head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            # head_bucket может быть запрещён политикой — пробуем список
            try:
                self._connect().list_objects_v2(
                    Bucket=self.bucket, Prefix=self.prefix, MaxKeys=1)
                return True
            except Exception as e:
                raise BackendError(f"S3 недоступен: {e}") from e

    def _key(self, remote_path):
        prefix = f"{self.prefix}/" if self.prefix else ""
        return prefix + str(remote_path).replace("\\", "/").lstrip("/")

    # — файлы —

    def upload(self, local_path, remote_path) -> bool:
        client = self._connect()
        if local_path.is_dir():
            for item in local_path.rglob("*"):
                if item.is_file():
                    client.upload_file(
                        str(item), self.bucket,
                        self._key(remote_path / item.relative_to(local_path)))
        else:
            client.upload_file(str(local_path), self.bucket,
                               self._key(remote_path))
        # локальная копия — чтобы restore/stats работали без сети
        dest = self.base_path / remote_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if local_path.is_file():
            dest.write_bytes(local_path.read_bytes())
        return True

    def download(self, remote_path, local_path) -> bool:
        client = self._connect()
        if local_path.is_dir() or True:
            local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.download_file(self.bucket, self._key(remote_path),
                                 str(local_path))
            return True
        except Exception:
            # запасной путь: локальный кэш
            cached = self.base_path / remote_path
            if cached.exists():
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(cached.read_bytes())
                return True
            return False

    def list_remote(self, remote_path):
        client = self._connect()
        prefix = self._key(remote_path)
        keys = []
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(Path(obj["Key"][len(prefix):]))
        except Exception:
            pass
        return keys

    def delete_remote(self, remote_path) -> bool:
        client = self._connect()
        try:
            client.delete_object(Bucket=self.bucket, Key=self._key(remote_path))
            cached = self.base_path / remote_path
            if cached.exists():
                cached.unlink()
            return True
        except Exception:
            return False

    def get_status(self):
        return {
            "backend": "s3",
            "bucket": self.bucket,
            "endpoint": self.settings.get("endpoint") or "aws",
            "prefix": self.prefix,
            "base_path": str(self.base_path),
            "synced_items": len(list(self.base_path.rglob("*")))
            if self.base_path.exists() else 0,
        }


class RcloneBackend(CloudBackend):
    """Облако через rclone (Google Drive, Dropbox и десятки других).

    Обходит отсутствие python-библиотек: rclone — отдельный бинарник,
    который уже умеет всё. FlamQuency лишь держит локальное зеркало и
    синкает его командой ``rclone sync``.
    """

    kind = "cloud"

    def __init__(self, remote, base_path, name):
        self.remote = remote            # например "gdrive:flamquency"
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.error = None

    def authenticate(self) -> bool:
        if not shutil.which("rclone"):
            self.error = "rclone не установлен"
            return False
        import subprocess
        proc = subprocess.run(["rclone", "about", f"{self.remote}:"],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            self.error = (proc.stderr or "rclone не авторизован").strip()
            return False
        return True

    def push(self) -> bool:
        """Залить локальное зеркало в облако."""
        import subprocess
        proc = subprocess.run(
            ["rclone", "sync", str(self.base_path), f"{self.remote}:"],
            capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            self.error = (proc.stderr or proc.stdout or "rclone sync упал").strip()
            return False
        return True

    def pull(self) -> bool:
        import subprocess
        proc = subprocess.run(
            ["rclone", "sync", f"{self.remote}:", str(self.base_path)],
            capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            self.error = (proc.stderr or proc.stdout or "rclone sync упал").strip()
            return False
        return True

    def upload(self, local_path, remote_path) -> bool:
        # Локально кладём всегда; в облако уходит пачкой через push().
        dest = self.base_path / remote_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if local_path.is_dir():
            for item in local_path.rglob("*"):
                if item.is_file():
                    target = dest / item.relative_to(local_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(item.read_bytes())
        else:
            dest.write_bytes(local_path.read_bytes())
        return True

    def download(self, remote_path, local_path) -> bool:
        self.pull()
        source = self.base_path / remote_path
        if source.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(source.read_bytes())
            return True
        return False

    def list_remote(self, remote_path):
        remote = self.base_path / remote_path
        if remote.exists():
            return [f.relative_to(remote) for f in remote.rglob("*")
                    if f.is_file()]
        return []

    def delete_remote(self, remote_path) -> bool:
        target = self.base_path / remote_path
        if target.exists() and target.is_file():
            target.unlink()
            return True
        return False

    def get_status(self):
        return {
            "backend": self.name,
            "remote": self.remote,
            "rclone": bool(shutil.which("rclone")),
            "error": self.error,
            "base_path": str(self.base_path),
            "synced_items": len(list(self.base_path.rglob("*")))
            if self.base_path.exists() else 0,
        }


# ── фабрика ───────────────────────────────────────────────────

def create_backend(config, name=None, base_path=None):
    """Создать бэкенд по имени или взять активный из конфига.

    Честно падает с BackendError, если бэкенду не хватает библиотеки,
    настройки или секрета. Отката на LocalBackend тут нет намеренно:
    пользователь должен знать, что его облако не подключено.
    """
    name = name or config.get("cloud_backend", "local")
    if name not in BACKENDS:
        raise BackendError(
            f"Неизвестный бэкенд: {name!r} (есть: {', '.join(backend_names())})")

    settings = config.get("backends", {}).get(name, {}) or {}
    base = Path(base_path) if base_path else Path.home() / ".flamquency" / "sync"

    if name == "local":
        return LocalBackend(base_path=base)

    if name == "s3":
        ok, problems, _ = describe_backend(config, name)
        if not ok:
            raise BackendError("; ".join(problems))
        return S3Backend(settings, base_path=base)

    if name in ("smb", "nfs"):
        ok, problems, _ = describe_backend(config, name)
        if not ok:
            raise BackendError("; ".join(problems))
        mount = Path(settings["mount_point"]).expanduser()
        return NetworkBackend(base, name, mount)

    if name == "github":
        from flamquency.github_backend import GitHubBackend
        return GitHubBackend(config.get("cloud_repo_name"),
                             os.environ.get(settings.get("token_env") or "")
                             or None)

    if name in ("gdrive", "dropbox"):
        ok, problems, _ = describe_backend(config, name)
        if not ok:
            raise BackendError("; ".join(problems))
        remote = ("gdrive" if name == "gdrive" else "dropbox")
        folder = (settings.get("folder_id") if name == "gdrive"
                  else settings.get("path", "").strip("/"))
        return RcloneBackend(f"{remote}:{folder}", base_path=base, name=name)

    raise BackendError(f"Бэкенд {name!r} ещё не реализован")


def available_backends(config):
    """[(имя, title, ok, проблемы)] — что можно выбрать прямо сейчас."""
    rows = []
    for name in backend_names():
        ok, problems, _ = describe_backend(config, name)
        rows.append((name, BACKENDS[name]["title"], ok, problems))
    return rows
