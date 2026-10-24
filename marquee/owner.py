"""Requests, the owner's pages (all requests, members, who's watching, problem reports) and notifications."""
import time
import asyncio
import logging

from aiohttp import web

from . import store, plex, push, recs, requests as reqs

log = logging.getLogger("marquee")
ONLINE_FOR = 180                                          # active in the last 3 minutes = online
_reports_at: dict = {}


def _owner(request):
    if not request["who"].get("owner"):
        raise web.HTTPForbidden()


# ---------- requests ----------
async def make_request(request):
    d = await request.json()
    out = await reqs.create(request["who"], str(d.get("id", "")), str(d.get("title") or d.get("name") or ""), d.get("year"))
    return web.json_response(out, status=400 if "error" in out else 200)


async def my_requests(request):
    return web.json_response(reqs.mine(request["who"]["id"]))


async def cancel_request(request):
    return web.json_response({"result": reqs.cancel(request["who"]["id"], str((await request.json()).get("id", "")))})


async def all_requests(request):
    _owner(request)
    items = sorted(reqs.all_(), key=lambda r: -r["at"])
    return web.json_response({"pending": [r for r in items if r["status"] == "pending"],
                              "waiting": [r for r in items if r["status"] == "approved"],
                              "reasons": {k: v[0] for k, v in reqs.DECLINES.items()}})


async def decide(request):
    _owner(request)
    d = await request.json()
    return web.json_response({"result": reqs.decide(request.match_info["id"], bool(d.get("approve")),
                                                    d.get("reason", "space"), d.get("custom", ""))})


async def complete(request):
    _owner(request)
    return web.json_response({"result": reqs.complete(request.match_info["id"])})


# ---------- members, who's watching, problem reports ----------
async def people(request):
    _owner(request)
    members, now, items = store.load("members.json", {}), time.time(), reqs.all_()
    out = [{"name": m.get("name"), "username": m.get("username", ""), "first": m.get("first", 0),
            "last": m.get("last", m.get("first", 0)), "online": now - m.get("last", 0) < ONLINE_FOR,
            "requests": sum(1 for r in items if str(r["user"]) == uid)} for uid, m in members.items()]
    missing = sorted((u for u in await plex.shared_users() if str(u["id"]) not in members),
                     key=lambda u: (u["name"] or "").lower())
    return web.json_response({"people": sorted(out, key=lambda x: (not x["online"], -x["last"])), "missing": missing,
                              "reports": list(reversed(store.load("reports.json", [])))[:30]})


async def watching(request):
    _owner(request)
    out = []
    for m in (await plex.get("/status/sessions") or {}).get("Metadata", []):
        it = plex.item(m)
        player, sess, trans = m.get("Player", {}), m.get("Session", {}), m.get("TranscodeSession")
        dur, off = int(m.get("duration") or 0), int(m.get("viewOffset") or 0)
        out.append({**it, "user": (m.get("User") or {}).get("title", "someone"), "state": player.get("state", "playing"),
                    "device": player.get("title") or player.get("product") or "", "remote": not player.get("local", True),
                    "progress": round(100 * off / dur) if dur else 0, "left": max(0, round((dur - off) / 60000)) if dur else 0,
                    "quality": plex.resolution((m.get("Media") or [{}])[0]),
                    "how": ("Converting" + (" video" if trans.get("videoDecision") == "transcode" else " audio"))
                           if trans else "Direct play",
                    "bandwidth": round(int(sess.get("bandwidth") or 0) / 1000, 1)})
    return web.json_response(out)


async def report(request):
    """Report a problem - from the sign-in screen (anyone; 3 an hour) or inside the app. Goes to the owner."""
    from .server import session, device
    who = session(request)
    ip = request.headers.get("X-Forwarded-For", request.remote or "?").split(",")[-1].strip()
    key = str(who["id"]) if who else ip
    recent = [t for t in _reports_at.get(key, []) if time.time() - t < 3600]
    if len(recent) >= (6 if who else 3):
        return web.json_response({"error": "Thanks - we've got your report. Please wait a bit before sending another."},
                                 status=429)
    d = await request.json()
    clean = lambda v, n: str(v or "").replace("@", "(at)").strip()[:n]       # no pings in Discord alerts
    text = clean(d.get("text"), 1000)
    if len(text) < 3:
        return web.json_response({"error": "Please tell us what happened."}, status=400)
    _reports_at[key] = recent + [time.time()]
    entry = {"at": time.time(), "name": who["name"] if who else (clean(d.get("name"), 60) or "Someone (not signed in)"),
             "contact": clean(d.get("contact"), 120), "where": "in the app" if who else "sign-in screen",
             "device": device(request), "text": text}
    store.save("reports.json", (store.load("reports.json", []) + [entry])[-200:])
    await push.owner_alert("🛠️ Problem report", f"{entry['name']}" + (f" ({entry['contact']})" if entry["contact"] else "")
                           + f" - {entry['where']}, {entry['device']}: {text[:300]}", "members")
    return web.json_response({"ok": True, "result": "Thanks - your report was sent. We'll take a look."})


async def ping(request):
    return web.json_response({"ok": True})               # the sign-in check already noted they're here


# ---------- notifications ----------
async def push_key(request):
    return web.json_response({"key": push.public_key()})


async def push_subscribe(request):
    who = request["who"]
    push.subscribe(who["id"], await request.json())
    await push.send([who["id"]], "Notifications on", "You'll hear about new requests here." if who.get("owner") else
                    "You'll hear when new movies and shows arrive, and about your requests.", "home")
    return web.json_response({"ok": True})


async def _new_arrivals():
    """Every 15 minutes: one notification to everyone about new movies, shows and seasons."""
    await asyncio.sleep(60)
    while True:
        try:
            state = store.load("new_state.json", {})
            added = (await plex.get("/library/recentlyAdded", {"X-Plex-Container-Size": 50}) or {}).get("Metadata", [])
            newest = max([int(m.get("addedAt", 0)) for m in added] or [0])
            last = state.get("last", 0)
            if last and newest > last:                    # (the first run only remembers where things are)
                names, seen = [], set()
                for m in sorted(added, key=lambda m: int(m.get("addedAt", 0))):
                    if int(m.get("addedAt", 0)) <= last or m.get("type") == "episode":
                        continue
                    it = plex.item(m)
                    label = it["title"] + (f" ({it['year']})" if it["type"] == "movie" and it["year"] else "") + \
                        (f" - {it['line'].lower()}" if m.get("type") == "season" else "")
                    if label not in seen:
                        seen.add(label)
                        names.append(label)
                if names:
                    owner = str((await plex.server()).get("owner_id"))
                    text = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
                    push.send_soon([u for u in push.subscribed() if u != owner], "🍿 New arrivals", text, "home")
            state["last"] = max(newest, last)
            store.save("new_state.json", state)
        except Exception as e:
            log.info(f"New arrivals check: {e}")
        await asyncio.sleep(15 * 60)


def routes(r):
    r.add_post("/api/request", make_request)
    r.add_get("/api/requests", my_requests)
    r.add_post("/api/requests/cancel", cancel_request)
    r.add_get("/api/all-requests", all_requests)
    r.add_post("/api/approvals/{id}", decide)
    r.add_post("/api/complete/{id}", complete)
    r.add_get("/api/people", people)
    r.add_get("/api/watching", watching)
    r.add_post("/api/report", report)
    r.add_post("/api/ping", ping)
    r.add_get("/api/push/key", push_key)
    r.add_post("/api/push/subscribe", push_subscribe)


async def background(app):
    loop = asyncio.get_running_loop()
    loop.create_task(reqs.watch())
    loop.create_task(recs.loop())
    loop.create_task(_new_arrivals())
    srv = await plex.server()
    log.info(f"Connected to Plex server \"{srv.get('name')}\" (owner: {srv.get('owner_name')})")
