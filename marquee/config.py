"""Marquee settings - read from a .env file next to the project (or real environment variables).

Required:
  PLEX_URL      your Plex server, e.g. http://192.168.1.20:32400
  PLEX_TOKEN    your Plex token (see the README: any movie > ... > Get Info > View XML > the X-Plex-Token at the end
                of the address)
  PUBLIC_URL    the https address people open Marquee at, e.g. https://marquee.example.com
Optional:
  PORT          web port Marquee listens on (default 8484)
  HOST          address to listen on (default 127.0.0.1 - put a reverse proxy / tunnel in front; 0.0.0.0 for Docker)
  DATA_DIR      where Marquee keeps its data (default ./data)
  BLOCK_ANIME   "true" to decline anime requests automatically (default false)
  REVIEW_TIME   how long requests usually take, shown to people (default "24-48 hours")
  OLLAMA_URL    an Ollama server for smarter plot matching (optional, e.g. http://localhost:11434)
  EMBED_MODEL   Ollama embedding model (default nomic-embed-text)
  OWNER_NAME    how people should refer to you in messages (default "the server owner")
  ALERT_WEBHOOK a Discord (or Slack-compatible) webhook URL - your alerts (new requests, new members, problem
                reports) are also posted there (optional)
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


PLEX_URL = _get("PLEX_URL").rstrip("/")
PLEX_TOKEN = _get("PLEX_TOKEN").split("&")[0]
PUBLIC_URL = _get("PUBLIC_URL").rstrip("/")
PORT = int(_get("PORT", "8484") or 8484)
HOST = _get("HOST", "127.0.0.1")
DATA_DIR = Path(_get("DATA_DIR", str(ROOT / "data"))).expanduser()
BLOCK_ANIME = _get("BLOCK_ANIME", "false").lower() in ("1", "true", "yes", "on")
REVIEW_TIME = _get("REVIEW_TIME", "24-48 hours")
OLLAMA_URL = _get("OLLAMA_URL").rstrip("/")
EMBED_MODEL = _get("EMBED_MODEL", "nomic-embed-text")
OWNER_NAME = _get("OWNER_NAME", "the server owner")
ALERT_WEBHOOK = _get("ALERT_WEBHOOK")

DATA_DIR.mkdir(parents=True, exist_ok=True)


def problems() -> list[str]:
    """What's missing before Marquee can run (shown at startup)."""
    out = []
    if not PLEX_URL:
        out.append("PLEX_URL is not set (your Plex server's address, e.g. http://192.168.1.20:32400)")
    if not PLEX_TOKEN:
        out.append("PLEX_TOKEN is not set (see the README for how to find it)")
    if not PUBLIC_URL:
        out.append("PUBLIC_URL is not set (the https address people will open Marquee at)")
    elif not PUBLIC_URL.startswith("https://"):
        out.append("PUBLIC_URL must start with https:// (Plex sign-in and notifications need it)")
    return out
