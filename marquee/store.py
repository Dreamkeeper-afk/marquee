"""Tiny JSON file store in DATA_DIR (requests, members, notifications, reports, ...)."""
import os
import json
import secrets
import threading
from pathlib import Path

from .config import DATA_DIR

_lock = threading.Lock()


def path(name: str) -> Path:
    return DATA_DIR / name


def load(name: str, default):
    try:
        return json.loads(path(name).read_text())
    except Exception:
        return default


def save(name: str, data):
    with _lock:
        tmp = path(name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path(name))


def secret(name: str, make=lambda: secrets.token_hex(32)) -> str:
    """A value made once and kept private (file mode 600)."""
    p = path(name)
    if p.exists():
        return p.read_text().strip()
    value = make()
    p.write_text(value)
    os.chmod(p, 0o600)
    return value
