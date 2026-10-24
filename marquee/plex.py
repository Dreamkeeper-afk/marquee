"""Talking to your Plex server and plex.tv."""
import re
import time
import logging
import urllib.parse
import xml.etree.ElementTree as ET

import aiohttp

from . import config, store

log = logging.getLogger("marquee.plex")
PLEX_TV = "https://plex.tv/api/v2"
_server: dict = {}
_shared = {"at": 0.0, "users": []}


def client_id() -> str:
    return store.secret("client_id", lambda: "marquee-" + __import__("secrets").token_hex(8))


def tv_headers(token: str | None = None) -> dict:
    h = {"Accept": "application/json", "X-Plex-Product": "Marquee", "X-Plex-Client-Identifier": client_id()}
    if token:
        h["X-Plex-Token"] = token
    return h


def _headers() -> dict:
    return {"X-Plex-Token": config.PLEX_TOKEN, "Accept": "application/json"}


async def get(path: str, params: dict | None = None, timeout: int = 20) -> dict | None:
    """GET from the Plex server; the MediaContainer dict, or None if it can't be reached."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.get(f"{config.PLEX_URL}{path}", params=params or {}, headers=_headers(), ssl=False) as r:
                if r.status == 200:
                    return (await r.json(content_type=None)).get("MediaContainer", {})
                log.info(f"Plex {path}: HTTP {r.status}")
    except Exception as e:
        log.info(f"Plex {path}: {e}")
    return None


async def image(path: str, width: int) -> tuple[bytes, str] | None:
    """A poster/backdrop from Plex, resized (the Plex token never reaches anyone's phone)."""
    params = {"width": width, "height": int(width * 1.5), "minSize": 1, "upscale": 1, "url": path}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(f"{config.PLEX_URL}/photo/:/transcode", params=params, headers=_headers(), ssl=False) as r:
                if r.status == 200:
                    return await r.read(), r.headers.get("Content-Type", "image/jpeg")
    except Exception:
        pass
    return None


async def server() -> dict:
    """{"machine": server id, "owner_id": plex.tv id of the token's owner, "name": server name}."""
    if not _server.get("machine"):
        ident = await get("/identity") or {}
        _server["machine"] = ident.get("machineIdentifier", "")
        root = await get("/") or {}
        _server["name"] = root.get("friendlyName", "Plex")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(f"{PLEX_TV}/user", headers=tv_headers(config.PLEX_TOKEN)) as r:
                    me = await r.json(content_type=None)
                    _server["owner_id"], _server["owner_name"] = me.get("id"), me.get("friendlyName") or me.get("username")
        except Exception as e:
            log.warning(f"Couldn't read the owner's plex.tv account: {e}")
    return _server


async def shared_users() -> list[dict]:
    """Everyone the server is shared with (plex.tv), refreshed every 10 minutes."""
    if time.time() - _shared["at"] < 600:
        return _shared["users"]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get("https://plex.tv/api/users", headers=tv_headers(config.PLEX_TOKEN)) as r:
                root = ET.fromstring(await r.read())
        _shared["users"] = [{"id": u.get("id"), "name": u.get("title") or u.get("username"), "username": u.get("username", "")}
                            for u in root.findall("User")]
        _shared["at"] = time.time()
    except Exception as e:
        log.info(f"Shared users: {e}")
    return _shared["users"]


def norm(title) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()


def thumb(m: dict) -> str:
    if m.get("type") == "episode":
        return m.get("grandparentThumb") or m.get("parentThumb") or m.get("thumb") or ""
    return m.get("thumb") or m.get("parentThumb") or ""


def item(m: dict) -> dict:
    """A movie/show card from any Plex item (an episode or season becomes its show)."""
    kind = m.get("type")
    if kind == "episode":
        key, title = m.get("grandparentRatingKey"), m.get("grandparentTitle", "")
        line = f"S{m.get('parentIndex', 0):02}E{m.get('index', 0):02} · {m.get('title', '')}"
    elif kind == "season":
        key, title = m.get("parentRatingKey"), m.get("parentTitle", "")
        line = "New show" if m.get("index") == 1 else f"New season {m.get('index')}"
    else:
        key, title, line = m.get("ratingKey"), m.get("title", ""), ""
    return {"key": str(key or ""), "title": title, "year": m.get("year") or m.get("parentYear") or "",
            "type": "show" if kind in ("episode", "season", "show") else "movie", "line": line, "thumb": thumb(m)}


def group(it: dict) -> str:
    """The same movie/show in several libraries (4K, HD, 3D...) is one entry: title + year + kind."""
    return f"{it['type']}|{norm(it['title'])}|{it['year']}"


def imdb_ids(m: dict) -> set:
    return {g["id"].replace("imdb://", "") for g in m.get("Guid", []) if "imdb://" in g.get("id", "")}


def tidy_edition(label) -> str:
    """'EXTENDED Extended Cut' -> 'Extended Cut' (Plex's edition + the file name's, without repeats or shouting)."""
    words, seen = [], set()
    for w in str(label or "").split():
        if w.lower() not in seen:
            seen.add(w.lower())
            words.append(w.capitalize() if w.isupper() and len(w) > 3 and w not in ("IMAX", "HDR10", "UHD") else w)
    return " ".join(words)


def edition_from_file(path: str) -> str:
    """'{edition-Director's Cut}' in a file name -> "Director's Cut"."""
    m = re.search(r"\{edition-([^}]+)\}", path or "")
    return m.group(1) if m else ""


def resolution(md: dict) -> str:
    r = (md.get("videoResolution") or "").upper()
    return "4K" if r == "4K" else (r + "p" if r.isdigit() else r)


async def on_plex(title: str, year=None) -> bool:
    """Is a movie/show with this name (and year, if given) already on the server?"""
    found = (await get("/search", {"query": re.sub(r"\s*\(\d{4}\)\s*$", "", title), "limit": 20}) or {}).get("Metadata", [])
    want = norm(re.sub(r"\s*\(\d{4}\)\s*$", "", title))
    return any(m.get("type") in ("movie", "show") and norm(m.get("title")) == want
               and (not year or str(m.get("year")) == str(year)) for m in found)


def play_link(machine: str, key: str) -> str:
    return (f"https://app.plex.tv/desktop/#!/server/{machine}/details?key="
            + urllib.parse.quote(f"/library/metadata/{key}", safe=""))
