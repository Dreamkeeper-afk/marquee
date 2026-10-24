"""Requests: people ask for movies/shows that aren't on the server; the owner approves or declines in the app.

  - already on the server? -> told so, nothing to request
  - BLOCK_ANIME=true -> anime is declined automatically
  - the owner's own requests are approved straight away (just a name)
  - approved requests are watched: when the title shows up on the server, the requester is told
  - people can cancel their own request until it's on the server; the owner can "mark complete"
Stored in DATA_DIR/requests.json.
"""
import time
import uuid
import asyncio
import logging

from . import config, store, plex, push, imdb

log = logging.getLogger("marquee.requests")
FILE = "requests.json"
WATCH_EVERY, GIVE_UP_DAYS = 10 * 60, 60

APPROVED = ("✅ Great news - your request for {title} was approved! It's usually added within " + config.REVIEW_TIME +
            ", and you'll get a notification the moment it's ready to watch. 🎬")
AVAILABLE = "🎉 Great news! {title} is now available. Grab some popcorn and enjoy! 🍿"
ANIME = ("Thanks so much for the request! 🙏 Anime isn't added to this server, so {title} won't be coming - sorry about "
         "that. Feel free to request any other movie or show!")
DECLINES = {
    "space": ("💾 Storage space", "Thanks so much for the request! Storage is limited right now, so we're going to pass on "
              "{title} for the moment. Please feel free to request something else anytime! 🙂"),
    "quality": ("🔍 Couldn't find a good copy", "Thanks for the request! We couldn't find a good-quality copy of {title} "
                "right now. Please request it again in a few weeks - a better copy is often out by then! 🙂"),
    "similar": ("🎬 Already have something similar", "Thanks for the suggestion! We're going to pass on {title} for now since "
                "there's something very similar on the server already. Feel free to request anything else! 🍿"),
    "anime": ("🚫 Anime", ANIME),
}


def all_() -> list:
    return store.load(FILE, [])


def _save(items):
    store.save(FILE, items)


def mine(user_id) -> list:
    return sorted((r for r in all_() if str(r["user"]) == str(user_id)), key=lambda r: -r["at"])


def _find(items, rid):
    return next((r for r in items if r["id"] == rid), None)


async def create(who: dict, imdb_id: str = "", title: str = "", year=None) -> dict:
    """{"result": message, "status": ...}. who = the signed-in person ({id, name, owner})."""
    shown = (title or "").strip()[:120] + (f" ({year})" if year and str(year) not in (title or "") else "")
    if who.get("owner"):                                  # yours: approved straight away, just a name
        if not shown:
            return {"error": "Type the name of the movie or show."}
        if await plex.on_plex(title or shown, None):
            return {"result": f"{shown} is already on the server.", "status": "available"}
        items = all_()
        items.append({"id": uuid.uuid4().hex[:10], "user": who["id"], "name": who["name"], "title": shown,
                      "imdb": imdb_id if imdb.IMDB_ID.fullmatch(imdb_id or "") else "", "status": "approved",
                      "note": "Auto-approved - you'll get a notification when it's ready", "at": time.time(),
                      "approved_at": time.time(), "owner": True})
        _save(items)
        return {"result": f"✅ {shown} is on the wanted list.", "status": "approved"}
    if not imdb.IMDB_ID.fullmatch(imdb_id or ""):
        return {"error": "Pick a title from the search results."}
    if await plex.on_plex(title, year):
        return {"result": f"{shown} is already on the server - no need to request it! 🍿", "status": "available"}
    if config.BLOCK_ANIME and await imdb.is_anime(imdb_id, title):
        return {"result": ANIME.format(title=shown), "status": "declined"}
    items = all_()
    if any(str(r["user"]) == str(who["id"]) and r["imdb"] == imdb_id and r["status"] in ("pending", "approved") for r in items):
        return {"result": f"You've already requested {shown}.", "status": "pending"}
    items.append({"id": uuid.uuid4().hex[:10], "user": who["id"], "name": who["name"], "title": shown, "imdb": imdb_id,
                  "status": "pending", "note": "Sent for approval", "at": time.time()})
    _save(items)
    await push.owner_alert("🎬 New request", f"{who['name']} would like {shown}. Tap to approve or decline.", "approvals")
    log.info(f"Request from {who['name']}: {shown}")
    return {"result": f"Request for {shown} sent! Requests are usually reviewed within {config.REVIEW_TIME} - you'll get "
                      f"a notification with the answer.", "status": "pending"}


def _tell(r: dict, title: str, text: str):
    push.send_soon([r["user"]], title, text, "requests")


def decide(rid: str, approve: bool, reason: str = "space", custom: str = "") -> str:
    items = all_()
    r = _find(items, rid)
    if not r or r["status"] != "pending":
        return "That request was already answered."
    if approve:
        r.update(status="approved", approved_at=time.time(), note=APPROVED.format(title=r["title"]))
        _tell(r, "✅ Request approved", r["note"])
    else:
        text = custom.strip()[:400] or DECLINES.get(reason, DECLINES["space"])[1].format(title=r["title"])
        r.update(status="declined", note=text)
        _tell(r, "Request update", text)
    r["decided_at"] = time.time()
    _save(items)
    return "Approved ✅" if approve else "Declined ❌"


def cancel(user_id, rid: str) -> str:
    items = all_()
    r = _find(items, rid)
    if not r or str(r["user"]) != str(user_id) or r["status"] not in ("pending", "approved"):
        return "That request can't be cancelled now."
    _save([x for x in items if x is not r])
    return f"Cancelled your request for {r['title']}."


def complete(rid: str) -> str:
    """Owner: an approved request is done - the requester hears it's ready, then it leaves the list."""
    items = all_()
    r = _find(items, rid)
    if not r or r["status"] != "approved":
        return "Already done."
    r.update(status="available", note=AVAILABLE.format(title=r["title"]), done_at=time.time())
    if not r.get("owner"):
        _tell(r, "🎉 Now available", r["note"])
    _save(items)
    return f"✅ {r['title']} marked complete"


async def watch():
    """Every 10 minutes: approved requests that have shown up on the server -> the requester is told."""
    while True:
        await asyncio.sleep(WATCH_EVERY)
        try:
            items, changed = all_(), False
            for r in items:
                if r["status"] != "approved":
                    continue
                if await plex.on_plex(r["title"]):
                    r.update(status="available", note=AVAILABLE.format(title=r["title"]), done_at=time.time())
                    _tell(r, "🎉 Now available", r["note"])
                    changed = True
                elif time.time() - r.get("approved_at", 0) > GIVE_UP_DAYS * 86400:
                    r.update(status="declined", note="We weren't able to add this one - sorry!")
                    changed = True
            if changed:
                _save(items)
        except Exception as e:
            log.info(f"Request watch: {e}")
