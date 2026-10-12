"""Content-addressable version store for FlamQuency-Sync.

Stores file blobs keyed by SHA256 hash (like git's object store),
with per-file version histories that reference those blobs.
Supports zlib compression, deduplication, and optional password-based
encryption (Fernet) of the stored blobs.
"""
import hashlib
import json
import os
import shutil
import zlib
from pathlib import Path
from datetime import datetime

from flamquency.encryption import EncryptionManager, EncryptionLockedError


class BlobStore:
    """Content-addressable blob storage with compression, dedup and encryption.

    When an :class:`EncryptionManager` is supplied and configured, every blob
    is compressed (optional) and then encrypted before hitting the disk. The
    blob index records per-blob whether it is encrypted, so a store that was
    plaintext before encryption was enabled keeps working.
    """

    def __init__(self, base_path, encryption=None):
        self.base_path = Path(base_path)
        self.blobs_dir = self.base_path / "blobs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.encryption = encryption
        self._index_path = self.base_path / "blob_index.json"
        self._index = self._load_index()

    def _load_index(self):
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_index(self):
        self._index_path.write_text(json.dumps(self._index, indent=2))

    def _blob_path(self, hash_hex):
        # Two-level fan-out like git: ab/cdef123...
        return self.blobs_dir / hash_hex[:2] / hash_hex[2:]

    def _require_writable_key(self):
        """Encrypted stores must never accept plaintext writes while locked."""
        if self.encryption is not None and self.encryption.is_configured:
            if not self.encryption.is_unlocked:
                raise EncryptionLockedError(
                    "Blob store is encrypted but locked — unlock it with the password first"
                )

    def _encrypt(self, payload):
        """Encrypt *payload* when the store is encrypted. Returns (bytes, flag)."""
        if self.encryption is not None and self.encryption.is_configured:
            self._require_writable_key()
            return self.encryption.encrypt(payload), True
        return payload, False

    def _decrypt(self, raw, entry):
        """Decrypt *raw* when the blob was stored encrypted."""
        if not entry.get("encrypted"):
            return raw
        if self.encryption is None:
            raise EncryptionLockedError(
                "Blob is encrypted but no encryption manager is available"
            )
        return self.encryption.decrypt(raw)

    def store(self, data, compress=True):
        """Store data, return its SHA256 hex digest. Deduplicates."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        hash_hex = hashlib.sha256(data).hexdigest()

        if hash_hex in self._index:
            return hash_hex  # Dedup — already stored

        blob_path = self._blob_path(hash_hex)
        blob_path.parent.mkdir(parents=True, exist_ok=True)

        payload = zlib.compress(data, level=6) if compress else data
        payload, encrypted = self._encrypt(payload)
        blob_path.write_bytes(payload)

        self._index[hash_hex] = {
            "size": len(data),
            "compressed": compress,
            "encrypted": encrypted,
            "stored_at": datetime.now().isoformat(),
        }
        self._save_index()
        return hash_hex

    def store_file(self, filepath, compress=True):
        """Store a file's contents, return hash. Streams in chunks for big files."""
        filepath = Path(filepath)
        h = hashlib.sha256()
        size = 0
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
                size += len(chunk)
        hash_hex = h.hexdigest()

        if hash_hex in self._index:
            return hash_hex  # Dedup

        blob_path = self._blob_path(hash_hex)
        blob_path.parent.mkdir(parents=True, exist_ok=True)

        if self.encryption is not None and self.encryption.is_configured:
            # Fernet works on whole messages — read, compress, encrypt, write.
            data = filepath.read_bytes()
            payload = zlib.compress(data, level=6) if compress else data
            payload, encrypted = self._encrypt(payload)
            blob_path.write_bytes(payload)
        elif compress:
            # Stream-compress to temp then move
            tmp = blob_path.with_suffix(".tmp")
            compressor = zlib.compressobj(level=6)
            with open(filepath, "rb") as fin, open(tmp, "wb") as fout:
                for chunk in iter(lambda: fin.read(1024 * 1024), b""):
                    fout.write(compressor.compress(chunk))
                fout.write(compressor.flush())
            tmp.rename(blob_path)
            encrypted = False
        else:
            shutil.copy2(filepath, blob_path)
            encrypted = False

        self._index[hash_hex] = {
            "size": size,
            "compressed": compress,
            "encrypted": encrypted,
            "stored_at": datetime.now().isoformat(),
        }
        self._save_index()
        return hash_hex

    def retrieve(self, hash_hex):
        """Retrieve blob data by hash. Returns bytes or None."""
        blob_path = self._blob_path(hash_hex)
        if not blob_path.exists():
            return None
        raw = blob_path.read_bytes()
        raw = self._decrypt(raw, self._index.get(hash_hex, {}))
        if self._index.get(hash_hex, {}).get("compressed", True):
            return zlib.decompress(raw)
        return raw

    def restore_to(self, hash_hex, dest_path):
        """Restore a blob directly to a destination file. Returns bool."""
        blob_path = self._blob_path(hash_hex)
        if not blob_path.exists():
            return False
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        entry = self._index.get(hash_hex, {})

        if entry.get("encrypted"):
            # Decrypt in memory, then write out (streaming cipher not possible).
            data = self.retrieve(hash_hex)
            if data is None:
                return False
            dest_path.write_bytes(data)
            return True

        if entry.get("compressed", True):
            decompressor = zlib.decompressobj()
            with open(blob_path, "rb") as fin, open(dest_path, "wb") as fout:
                for chunk in iter(lambda: fin.read(1024 * 1024), b""):
                    fout.write(decompressor.decompress(chunk))
                fout.write(decompressor.flush())
        else:
            shutil.copy2(blob_path, dest_path)
        return True

    def rekey(self, old_manager, new_manager):
        """Re-encrypt every encrypted blob from *old_manager* to *new_manager*."""
        rekeyed = 0
        for hash_hex in list(self._index.keys()):
            entry = self._index[hash_hex]
            if not entry.get("encrypted"):
                continue
            blob_path = self._blob_path(hash_hex)
            if not blob_path.exists():
                continue
            plain = old_manager.decrypt(blob_path.read_bytes())
            blob_path.write_bytes(new_manager.encrypt(plain))
            rekeyed += 1
        self._save_index()
        return rekeyed

    def disable_encryption(self, manager):
        """Decrypt every encrypted blob in place and drop the key file."""
        decrypted = 0
        for hash_hex in list(self._index.keys()):
            entry = self._index[hash_hex]
            if not entry.get("encrypted"):
                continue
            blob_path = self._blob_path(hash_hex)
            if not blob_path.exists():
                continue
            plain = manager.decrypt(blob_path.read_bytes())
            blob_path.write_bytes(plain)
            entry["encrypted"] = False
            decrypted += 1
        self._save_index()
        manager.disable()
        return decrypted

    def has(self, hash_hex):
        return hash_hex in self._index

    def stats(self):
        total_size = sum(b["size"] for b in self._index.values())
        stored_size = sum(
            self._blob_path(h).stat().st_size
            for h in self._index
            if self._blob_path(h).exists()
        )
        encrypted_count = sum(
            1 for b in self._index.values() if b.get("encrypted")
        )
        return {
            "blob_count": len(self._index),
            "uncompressed_bytes": total_size,
            "stored_bytes": stored_size,
            "ratio": round(total_size / stored_size, 2) if stored_size > 0 else 0,
            "encrypted_blobs": encrypted_count,
        }


class VersionStore:
    """Per-file version history referencing blobs in the BlobStore."""

    def __init__(self, base_path, encryption=None):
        self.base_path = Path(base_path)
        self.versions_dir = self.base_path / "files"
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.blob_store = BlobStore(base_path, encryption=encryption)
        self.encryption = encryption

    def _version_path(self, rel_path):
        # Sanitize rel_path for filesystem — replace / with __
        safe = str(rel_path).replace("/", "__").replace("\\", "__")
        safe = safe.lstrip(".") or "root"
        return self.versions_dir / (safe + ".json")

    def _load_history(self, rel_path):
        vp = self._version_path(rel_path)
        if vp.exists():
            try:
                return json.loads(vp.read_text())
            except Exception:
                return []
        return []

    def _save_history(self, rel_path, history):
        vp = self._version_path(rel_path)
        vp.parent.mkdir(parents=True, exist_ok=True)
        vp.write_text(json.dumps(history, indent=2))

    def record_version(self, rel_path, filepath=None, data=None, message=None):
        """Record a new version of a file. Stores content in blob store."""
        if data is None and filepath is not None:
            hash_hex = self.blob_store.store_file(filepath)
        elif data is not None:
            hash_hex = self.blob_store.store(data)
        else:
            raise ValueError("Either filepath or data must be provided")

        # Check if identical to latest version (skip duplicate)
        history = self._load_history(rel_path)
        if history and history[-1]["hash"] == hash_hex:
            return hash_hex, False  # No change

        entry = {
            "hash": hash_hex,
            "timestamp": datetime.now().isoformat(),
            "message": message or "",
        }
        history.append(entry)
        self._save_history(rel_path, history)
        return hash_hex, True  # New version recorded

    def get_history(self, rel_path):
        """Get full version history for a file."""
        return self._load_history(rel_path)

    def list_versions(self, rel_path):
        """Human-readable version list."""
        history = self._load_history(rel_path)
        result = []
        for i, entry in enumerate(history):
            blob_info = self.blob_store._index.get(entry["hash"], {})
            result.append({
                "index": i,
                "hash": entry["hash"][:12],
                "timestamp": entry["timestamp"],
                "message": entry.get("message", ""),
                "size": blob_info.get("size", "?"),
            })
        return result

    def restore_version(self, rel_path, version_index=None, dest_path=None):
        """Restore a file to a specific version.

        version_index=None → latest version.
        dest_path=None → overwrite the original file location.
        """
        history = self._load_history(rel_path)
        if not history:
            return False, "No version history found"

        if version_index is None:
            version_index = len(history) - 1

        if version_index < 0 or version_index >= len(history):
            return False, f"Version index {version_index} out of range (0-{len(history)-1})"

        target = history[version_index]
        hash_hex = target["hash"]

        if dest_path is None:
            # Restore to original location
            home = Path.home()
            dest_path = home / rel_path

        success = self.blob_store.restore_to(hash_hex, dest_path)
        if success:
            return True, f"Restored {rel_path} to version {version_index} (hash: {hash_hex[:12]}...)"
        return False, f"Blob {hash_hex[:12]}... not found in store"

    def restore_file_content(self, rel_path, version_index=None, dest_path=None):
        """Restore the *content* of a specific version to any destination.

        Unlike :meth:`restore_version`, this method supports an explicit
        ``dest_path`` (restoring to any location, not only the original)
        and returns richer information about the restored content.

        Parameters
        ----------
        rel_path:
            Path key used when the version was recorded.
        version_index:
            Which version to restore. ``None`` restores the latest.
        dest_path:
            Where to write the content. ``None`` restores to the original
            location (``~ / rel_path``) — same as ``restore_version``.

        Returns
        -------
        (ok: bool, message: str, info: dict)
            ``info`` carries ``hash``, ``size``, ``version_index``,
            ``version_count`` and ``dest_path`` (as ``str``).
        """
        history = self._load_history(rel_path)
        if not history:
            return False, "No version history found", {}

        if version_index is None:
            version_index = len(history) - 1

        if version_index < 0 or version_index >= len(history):
            return False, f"Version index {version_index} out of range (0-{len(history)-1})", {}

        hash_hex = history[version_index]["hash"]

        if dest_path is None:
            dest_path = Path.home() / rel_path
        dest_path = Path(dest_path)

        success = self.blob_store.restore_to(hash_hex, dest_path)
        if not success:
            return False, f"Blob {hash_hex[:12]}... not found in store", {}

        info = {
            "hash": hash_hex,
            "size": self.blob_store._index.get(hash_hex, {}).get("size", "?"),
            "version_index": version_index,
            "version_count": len(history),
            "dest_path": str(dest_path),
        }
        return True, (
            f"Restored content of {rel_path} (version {version_index}/"
            f"{len(history)-1}, {info['size']} B) to {dest_path}"
        ), info

    def view_file_content(self, rel_path, version_index=None, max_bytes=1_048_576):
        """Return the *content* of a version without restoring anything.

        Parameters
        ----------
        rel_path:
            Path key used when the version was recorded.
        version_index:
            Which version to read. ``None`` reads the latest.
        max_bytes:
            Hard cap on the returned content (1 MiB by default) to keep
            ``view-content`` from flooding the terminal with huge blobs.

        Returns
        -------
        (ok: bool, message: str, info: dict)
            ``info`` carries ``data`` (bytes), ``hash``, ``size``,
            ``version_index``, ``version_count`` and ``truncated``.
        """
        history = self._load_history(rel_path)
        if not history:
            return False, "No version history found", {}

        if version_index is None:
            version_index = len(history) - 1

        if version_index < 0 or version_index >= len(history):
            return False, f"Version index {version_index} out of range (0-{len(history)-1})", {}

        hash_hex = history[version_index]["hash"]
        data = self.blob_store.retrieve(hash_hex)
        if data is None:
            return False, f"Blob {hash_hex[:12]}... not found in store", {}

        truncated = len(data) > max_bytes
        info = {
            "data": data[:max_bytes],
            "hash": hash_hex,
            "size": len(data),
            "version_index": version_index,
            "version_count": len(history),
            "truncated": truncated,
        }
        msg = f"{rel_path} version {version_index}/{len(history)-1} ({info['size']} B)"
        if truncated:
            msg += f" — truncated to {max_bytes} B"
        return True, msg, info

    def tracked_keys(self):
        """All rel_path keys that have a version history."""
        if not self.versions_dir.exists():
            return []
        keys = []
        for vp in self.versions_dir.glob("*.json"):
            try:
                if json.loads(vp.read_text()):
                    keys.append(vp.stem.replace("__", "/"))
            except Exception:
                continue
        return sorted(keys)

    def restore_tree(self, prefix=None, dest_root=None, version_index=None,
                     progress=None):
        """Restore every tracked file under *prefix* at one version index.

        Parameters
        ----------
        prefix:
            Restrict to keys starting with this path (``None`` = everything).
        dest_root:
            Root the keys are restored under. ``None`` restores each file to
            its original location (``~ / rel_path``).
        version_index:
            Version to restore per file. ``None`` = the latest of each file.
        progress:
            Optional ``callable(done, total, rel_path)``.

        Returns
        -------
        dict with ``restored``, ``failed``, ``total`` and ``files``.
        """
        keys = self.tracked_keys()
        if prefix:
            prefix = str(prefix).replace("\\", "/").rstrip("/")
            keys = [k for k in keys
                    if k == prefix or k.startswith(prefix + "/")]
        if not keys:
            return {"restored": 0, "failed": 0, "total": 0, "files": []}

        restored, failed, files = 0, 0, []
        for done, key in enumerate(keys, 1):
            ok, msg, info = self.restore_file_content(
                key, version_index=version_index,
                dest_path=(Path(dest_root) / key) if dest_root else None,
            )
            if ok:
                restored += 1
                files.append({"rel_path": key, "dest": info.get("dest_path"),
                              "version_index": info.get("version_index")})
            else:
                failed += 1
            if progress:
                try:
                    progress(done, len(keys), key)
                except Exception:
                    pass
        return {"restored": restored, "failed": failed,
                "total": len(keys), "files": files}

    def diff_versions(self, rel_path, v1, v2):
        """Compare two versions of a file (text files only)."""
        history = self._load_history(rel_path)
        if v1 >= len(history) or v2 >= len(history):
            return None
        data1 = self.blob_store.retrieve(history[v1]["hash"])
        data2 = self.blob_store.retrieve(history[v2]["hash"])
        if data1 is None or data2 is None:
            return None
        try:
            text1 = data1.decode("utf-8").splitlines()
            text2 = data2.decode("utf-8").splitlines()
            import difflib
            diff = difflib.unified_diff(
                text1, text2,
                fromfile=f"v{v1}", tofile=f"v{v2}", lineterm=""
            )
            return "\n".join(diff)
        except UnicodeDecodeError:
            return "(binary files differ)"

    def prune(self, keep_last_n=50):
        """Remove old versions, keeping last N per file."""
        pruned = 0
        for vp in self.versions_dir.glob("*.json"):
            try:
                history = json.loads(vp.read_text())
                if len(history) > keep_last_n:
                    removed = history[:-keep_last_n]
                    vp.write_text(json.dumps(history[-keep_last_n:], indent=2))
                    pruned += len(removed)
            except Exception:
                continue
        return pruned

    def gc(self):
        """Garbage collect unreferenced blobs."""
        referenced = set()
        for vp in self.versions_dir.glob("*.json"):
            try:
                history = json.loads(vp.read_text())
                for entry in history:
                    referenced.add(entry["hash"])
            except Exception:
                continue

        removed = 0
        for hash_hex in list(self.blob_store._index.keys()):
            if hash_hex not in referenced:
                blob_path = self.blob_store._blob_path(hash_hex)
                if blob_path.exists():
                    blob_path.unlink()
                del self.blob_store._index[hash_hex]
                removed += 1
        self.blob_store._save_index()
        return removed

    def stats(self):
        file_count = len(list(self.versions_dir.glob("*.json")))
        return {
            "tracked_files": file_count,
            **self.blob_store.stats(),
        }

    def stats_by_type(self, limit=10):
        """Статистика по типам файлов: [(расширение, файлов, байт), ...]."""
        buckets = {}
        for key in self.tracked_keys():
            suffix = Path(key).suffix.lower().lstrip(".") or "(без расширения)"
            info = buckets.setdefault(suffix, {"files": 0, "bytes": 0})
            info["files"] += 1
            history = self.get_history(key)
            if history:
                blob = self.blob_store._index.get(history[-1]["hash"], {})
                info["bytes"] += int(blob.get("size", 0) or 0)
        ranked = sorted(buckets.items(),
                        key=lambda kv: (-kv[1]["bytes"], kv[0]))
        return [(ext, v["files"], v["bytes"]) for ext, v in ranked[:limit]]

    def top_changed_files(self, limit=10):
        """Файлы с наибольшим числом версий — «топ изменяемых»."""
        rows = []
        for key in self.tracked_keys():
            history = self.get_history(key)
            if not history:
                continue
            blob = self.blob_store._index.get(history[-1]["hash"], {})
            rows.append((key, len(history), int(blob.get("size", 0) or 0)))
        rows.sort(key=lambda r: (-r[1], -r[2], r[0]))
        return rows[:limit]
