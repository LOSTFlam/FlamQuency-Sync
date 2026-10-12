"""Content-addressable version store for FlamQuency-Sync.

Stores file blobs keyed by SHA256 hash (like git's object store),
with per-file version histories that reference those blobs.
Supports zlib compression and deduplication.
"""
import hashlib
import json
import os
import shutil
import zlib
from pathlib import Path
from datetime import datetime


class BlobStore:
    """Content-addressable blob storage with compression and dedup."""

    def __init__(self, base_path):
        self.base_path = Path(base_path)
        self.blobs_dir = self.base_path / "blobs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
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

    def store(self, data, compress=True):
        """Store data, return its SHA256 hex digest. Deduplicates."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        hash_hex = hashlib.sha256(data).hexdigest()

        if hash_hex in self._index:
            return hash_hex  # Dedup — already stored

        blob_path = self._blob_path(hash_hex)
        blob_path.parent.mkdir(parents=True, exist_ok=True)

        if compress:
            blob_path.write_bytes(zlib.compress(data, level=6))
        else:
            blob_path.write_bytes(data)

        self._index[hash_hex] = {
            "size": len(data),
            "compressed": compress,
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

        if compress:
            # Stream-compress to temp then move
            tmp = blob_path.with_suffix(".tmp")
            compressor = zlib.compressobj(level=6)
            with open(filepath, "rb") as fin, open(tmp, "wb") as fout:
                for chunk in iter(lambda: fin.read(1024 * 1024), b""):
                    fout.write(compressor.compress(chunk))
                fout.write(compressor.flush())
            tmp.rename(blob_path)
        else:
            shutil.copy2(filepath, blob_path)

        self._index[hash_hex] = {
            "size": size,
            "compressed": compress,
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
        if self._index.get(hash_hex, {}).get("compressed", True):
            decompressor = zlib.decompressobj()
            with open(blob_path, "rb") as fin, open(dest_path, "wb") as fout:
                for chunk in iter(lambda: fin.read(1024 * 1024), b""):
                    fout.write(decompressor.decompress(chunk))
                fout.write(decompressor.flush())
        else:
            shutil.copy2(blob_path, dest_path)
        return True

    def has(self, hash_hex):
        return hash_hex in self._index

    def stats(self):
        total_size = sum(b["size"] for b in self._index.values())
        stored_size = sum(
            self._blob_path(h).stat().st_size
            for h in self._index
            if self._blob_path(h).exists()
        )
        return {
            "blob_count": len(self._index),
            "uncompressed_bytes": total_size,
            "stored_bytes": stored_size,
            "ratio": round(total_size / stored_size, 2) if stored_size > 0 else 0,
        }


class VersionStore:
    """Per-file version history referencing blobs in the BlobStore."""

    def __init__(self, base_path):
        self.base_path = Path(base_path)
        self.versions_dir = self.base_path / "files"
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.blob_store = BlobStore(base_path)

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
