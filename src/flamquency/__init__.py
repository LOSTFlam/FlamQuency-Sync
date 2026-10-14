"""FlamQuency-Sync - Terminal-based file synchronization with rollback.

Единственный источник правды о версии. Упаковка (setup.py, PKGBUILD,
snapcraft, RPM spec) читает его, а не держит свою копию — иначе релиз
разъезжается.
"""
__version__ = "2.0.0"
