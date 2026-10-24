"""Marquee's web server: sign-in, the library pages, and the app itself. (Requests, owner pages and notifications
are in owner.py.)"""
import json
import time
import hmac
import base64
import hashlib
import logging
from pathlib import Path

import aiohttp
from aiohttp import web

from . import config, store, plex, imdb, push, recs

log = logging.getLogger("marquee")
WEB = Path(__file__).resolve().parent / "web"
COOKIE, SESSION_DAYS = "marquee", 90
OPEN = {"/api/auth/config", "/api/auth/finish", "/api/report"}       # usable before signing in
_fails: dict = {}
_seen_saved: dict = {}


# ---------- sessions: a signed cookie with who you are (no Plex token is ever kept) ----------
def _secret() -> bytes:
    return store.secret("session_secret").encode()


def _sign(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return f"{raw}.{hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()}"


def session(request) -> dict | None:
    value = request.cookies.get(COOKIE, "")
    if "." not in value:
        return None
    raw, sig = value.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except Exception:
        return None
    return data if data.get("exp", 0) > time.time() else None


@web.middleware
async def guard(request, handler):
    if request.path.startswith("/api/") and request.path not in OPEN:
        who = session(request)
        if not who:
            return web.json_response({"error": "sign in"}, status=401)
        request["who"] = who
        _note_seen(who)
    if request.path == "/img" and not session(request):
        return web.Response(status=401)
    return await handler(request)


def device(request) -> str:
    a = request.headers.get("User-Agent", "")
    return ("iPhone" if "iPhone" in a else "iPad" if "iPad" in a else "Android" if "Android" in a else
            "Mac" if "Macintosh" in a else "Windows PC" if "Windows" in a else "a device")


def _note_seen(who: dict):
    """Members: when each person last used Marquee (saved at most once a minute)."""
    if who.get("owner"):
        return
    uid, now = str(who["id"]), time.time()
    if now - _seen_saved.get(uid, 0) < 60:
        return
    _seen_saved[uid] = now
    members = store.load("members.json", {})
    m = members.setdefault(uid, {"name": who["name"], "first": now})
    m.update(name=who["name"], last=now)
    store.save("members.json", members)


# ---------- sign in with Plex (on Plex's own page - Marquee never sees a password) ----------
async def auth_config(request):
    """Each phone creates its own Plex sign-in code (so Plex doesn't warn about "another device"); it only needs
    Marquee's app id for that."""
    return web.json_response({"clientId": plex.client_id(), "product": "Marquee"})


async def auth_finish(request):
    ip = request.headers.get("X-Forwarded-For", request.remote or "?").split(",")[-1].strip()
    recent = [t for t in _fails.get(ip, []) if time.time() - t < 900]
    if len(recent) >= 10:
        return web.json_response({"error": "Too many tries - wait a few minutes."}, status=429)
    pin = str((await request.json()).get("pin", ""))
    if not pin.isdigit():
        return web.json_response({"error": "bad sign-in"}, status=400)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
        async with s.get(f"{plex.PLEX_TV}/pins/{pin}", headers=plex.tv_headers()) as r:
            token = (await r.json(content_type=None)).get("authToken")
        if not token:
            log.info(f"Sign-in not finished on Plex's page ({device(request)})")
            return web.json_response({"error": "Plex sign-in wasn't finished - please try again."}, status=401)
        async with s.get(f"{plex.PLEX_TV}/user", headers=plex.tv_headers(token)) as r:
            user = await r.json(content_type=None)
        srv = await plex.server()
        owner = user.get("id") == srv.get("owner_id")
        allowed = owner
        if not allowed:                                   # does this account have access to the server?
            async with s.get(f"{plex.PLEX_TV}/resources", params={"includeHttps": 1}, headers=plex.tv_headers(token)) as r:
                allowed = any(x.get("clientIdentifier") == srv.get("machine") for x in await r.json(content_type=None))
    if not allowed:                                       # (their token is dropped here - never stored)
        _fails[ip] = recent + [time.time()]
        log.info(f"{user.get('username')} turned away - no access to this server ({device(request)})")
        return web.json_response({"error": "This Plex account doesn't have access to this server."}, status=403)
    name = user.get("friendlyName") or user.get("title") or user.get("username") or "there"
    log.info(f"{user.get('username')} signed in ({device(request)})")
    if not owner:
        members = store.load("members.json", {})
        first = str(user["id"]) not in members
        m = members.setdefault(str(user["id"]), {"first": time.time()})
        m.update(name=name, username=user.get("username", ""), last=time.time())
        store.save("members.json", members)
        if first:
            await push.owner_alert("👋 New member", f"{name} started using Marquee.", "members")
    who = {"id": user["id"], "name": name, "acct": 1 if owner else user["id"], "owner": owner,
           "exp": int(time.time() + SESSION_DAYS * 86400)}
    resp = web.json_response({"ok": True, "name": name})
    resp.set_cookie(COOKIE, _sign(who), max_age=SESSION_DAYS * 86400, httponly=True, secure=True, samesite="Lax")
    return resp


async def sign_out(request):
    resp = web.json_response({"ok": True})
    resp.del_cookie(COOKIE)
    return resp


async def me(request):
    srv = await plex.server()
    return web.json_response({"name": request["who"]["name"], "owner": request["who"].get("owner", False),
                              "server": srv.get("name", "Plex"), "reviewTime": config.REVIEW_TIME,
                              "ownerName": config.OWNER_NAME})


# ---------- the library ----------
def _ago(ts) -> str:
    days = int((time.time() - int(ts or 0)) / 86400)
    return "added today" if days <= 0 else "added yesterday" if days == 1 else f"added {days} days ago"


async def home(request):
    added = (await plex.get("/library/recentlyAdded", {"X-Plex-Container-Size": 60}) or {}).get("Metadata", [])
    out_added, seen = [], set()
    for m in added:
        it = plex.item(m)
        if not it["key"] or plex.group(it) in seen:       # one entry per movie, however many copies
            continue
        seen.add(plex.group(it))
        it["line"] = f"{it['line'] + ' · ' if it['line'] else ''}{_ago(m.get('addedAt'))}"
        out_added.append(it)
        if len(out_added) >= 12:
            break
    released, today = [], time.strftime("%Y-%m-%d")
    for sec in (await plex.get("/library/sections") or {}).get("Directory", []):
        kind = {"movie": 1, "show": 4}.get(sec.get("type"))
        if not kind:
            continue
        params = {"type": kind, "sort": "originallyAvailableAt:desc", "X-Plex-Container-Size": 30}
        if kind == 4:
            params["index"] = 1                            # season premieres: new shows + new seasons
        released += (await plex.get(f"/library/sections/{sec['key']}/all", params) or {}).get("Metadata", [])
    released = sorted((m for m in released if m.get("originallyAvailableAt") and m["originallyAvailableAt"] <= today),
                      key=lambda m: m["originallyAvailableAt"], reverse=True)
    out_rel, seen = [], set()
    for m in released:
        it = plex.item(m)
        if m.get("type") == "episode":
            it["line"] = "New show" if m.get("parentIndex") == 1 else f"New season {m.get('parentIndex')}"
        if not it["key"] or plex.group(it) in seen:
            continue
        seen.add(plex.group(it))
        when = time.strftime("%b %-d", time.strptime(m["originallyAvailableAt"], "%Y-%m-%d"))
        it["line"] = f"{it['line'] + ' · ' if it['line'] else ''}{when}"
        out_rel.append(it)
        if len(out_rel) >= 12:
            break
    return web.json_response({"recs": recs.for_account(request["who"]["acct"])[:12], "releases": out_rel,
                              "added": out_added})


async def search(request):
    q = request.query.get("q", "").strip()
    if len(q) < 2:
        return web.json_response({"onPlex": [], "notYet": []})
    found = (await plex.get("/search", {"query": q, "limit": 30, "includeGuids": 1}) or {}).get("Metadata", [])
    on_plex, by_title, have = [], {}, set()
    for m in found:
        if m.get("type") not in ("movie", "show"):
            continue
        have |= plex.imdb_ids(m)
        tags = {plex.resolution(md) for md in m.get("Media", []) if md.get("videoResolution")}
        it = plex.item(m)
        g = plex.group(it)
        if g in by_title:                                 # the same title in two libraries: one result
            by_title[g]["tags"] = sorted(set(by_title[g]["tags"]) | tags, key=lambda t: (t != "4K", t))[:3]
            continue
        it["tags"] = sorted(tags, key=lambda t: (t != "4K", t))[:3]
        by_title[g] = it
        on_plex.append(it)
    names = {(plex.norm(i["title"]), str(i["year"])) for i in on_plex}
    not_yet = [c for c in await imdb.candidates(q, 5)                 # IMDb ids beat names
               if c["id"] not in have and (plex.norm(c["title"]), str(c.get("year") or "")) not in names]
    return web.json_response({"onPlex": on_plex[:12], "notYet": not_yet[:5]})


async def title(request):
    key = request.match_info["key"]
    if not key.isdigit():
        return web.json_response({"error": "not found"}, status=404)
    meta = (await plex.get(f"/library/metadata/{key}", {"includeMedia": 1}) or {}).get("Metadata", [])
    if not meta:
        return web.json_response({"error": "not found"}, status=404)
    m = meta[0]
    copies = [m]
    if m.get("type") == "movie":                          # the same movie in other libraries: one page, every edition
        for x in (await plex.get("/search", {"query": m.get("title", ""), "limit": 20}) or {}).get("Metadata", []):
            if (x.get("type") == "movie" and str(x.get("ratingKey")) != key
                    and plex.norm(x.get("title")) == plex.norm(m.get("title")) and x.get("year") == m.get("year")):
                copies += (await plex.get(f"/library/metadata/{x['ratingKey']}", {"includeMedia": 1}) or {}).get("Metadata", [])[:1]
    versions, seen = [], set()
    for c in copies:
        for md in c.get("Media", []):
            part = (md.get("Part") or [{}])[0].get("file", "")
            label = md.get("editionTitle") or c.get("editionTitle") or plex.edition_from_file(part)
            if "3d" in part.lower() and "3D" not in (label or ""):
                label = (label + " 3D").strip()
            v = {"label": plex.tidy_edition(label) or "Standard", "res": plex.resolution(md)}
            if (v["label"], v["res"]) not in seen:
                seen.add((v["label"], v["res"]))
                versions.append(v)
    versions.sort(key=lambda v: (v["res"] != "4K", v["label"] != "Standard", v["label"]))
    ids = plex.imdb_ids(m)
    srv = await plex.server()
    mins, kids = int(m.get("duration", 0) / 60000), m.get("childCount")
    return web.json_response({
        "key": key, "title": m.get("title"), "year": m.get("year", ""), "type": m.get("type"),
        "summary": m.get("summary", ""), "rating": m.get("contentRating", ""),
        "length": (f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m") if mins else
                  (f"{kids} season{'s' if kids != 1 else ''}" if kids else ""),
        "genres": [g.get("tag") for g in m.get("Genre", [])][:3], "versions": versions,
        "thumb": m.get("thumb", ""), "art": m.get("art", ""), "play": plex.play_link(srv.get("machine", ""), key),
        "imdb": f"https://www.imdb.com/title/{next(iter(ids))}/" if ids else ""})


async def image(request):
    path = request.query.get("u", "")
    if not path.startswith("/library/"):
        return web.Response(status=400)
    got = await plex.image(path, min(int(request.query.get("w", "300") or 300), 1200))
    if not got:
        return web.Response(status=404)
    return web.Response(body=got[0], content_type=got[1], headers={"Cache-Control": "private, max-age=86400"})


# ---------- the app ----------
async def page(request):
    return web.FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


async def service_worker(request):
    return web.FileResponse(WEB / "sw.js", headers={"Cache-Control": "no-cache", "Content-Type": "application/javascript"})


def build() -> web.Application:
    from . import owner
    app = web.Application(middlewares=[guard], client_max_size=64 * 1024)
    r = app.router
    r.add_get("/", page)
    r.add_get("/sw.js", service_worker)
    r.add_static("/static", WEB)
    r.add_get("/img", image)
    r.add_get("/api/auth/config", auth_config)
    r.add_post("/api/auth/finish", auth_finish)
    r.add_post("/api/auth/signout", sign_out)
    r.add_get("/api/me", me)
    r.add_get("/api/home", home)
    r.add_get("/api/search", search)
    r.add_get("/api/title/{key}", title)
    owner.routes(r)
    app.on_startup.append(owner.background)
    return app
