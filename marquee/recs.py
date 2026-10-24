"""Recommendations - each person's own picks, from what THEY watched on the server.

Rules: matched on plot and theme only (never actors, directors or title words); only titles already on the server;
never something they've watched (in any copy); one pick per franchise; a different "Because you watched ..." reason
for every pick. Refreshed nightly (and soon after Marquee starts).

Plot matching: with OLLAMA_URL set, an embedding model (EMBED_MODEL) understands each plot; without it, a built-in
word-weighting matcher (TF-IDF) that needs nothing extra. Results: DATA_DIR/recommendations.json.
"""
import re
import json
import math
import time
import asyncio
import hashlib
import logging
from collections import Counter
from datetime import datetime

import aiohttp

from . import config, store, plex

log = logging.getLogger("marquee.recs")
OUT, PER_PERSON, HISTORY_TITLES, NIGHTLY_AT = "recommendations.json", 12, 60, 4
STOP = set("""a an the and or but if then than of in on at to for from by with without about into over under after before
between through during is are was were be been being has have had do does did this that these those it its they them their
he she his her him who whom whose which what when where why how all any both each few more most other some such no nor not
only own same so too very can will just one two three new also out up down off again further once here there s t
""".split())
_SMALL = {"the", "a", "an", "of", "and", "part", "chapter", "movie", "film"}


async def _library() -> dict:
    items = {}
    for sec in (await plex.get("/library/sections") or {}).get("Directory", []):
        if sec.get("type") not in ("movie", "show"):
            continue
        for m in (await plex.get(f"/library/sections/{sec['key']}/all", timeout=120) or {}).get("Metadata", []):
            summary = (m.get("summary") or "").strip()
            if len(summary) < 40:
                continue
            genres = ", ".join(g.get("tag", "") for g in m.get("Genre", [])[:3])
            items[str(m["ratingKey"])] = {"title": m.get("title", ""), "year": m.get("year", ""), "type": sec["type"],
                                           "thumb": m.get("thumb", ""),
                                           "text": f"{genres + '. ' if genres else ''}{summary[:1200]}"}   # plot only
    return items


def _tfidf(lib: dict):
    """Built-in plot matcher: (keys, unit vectors as dicts)."""
    docs = {}
    for k, it in lib.items():
        words = [w for w in re.findall(r"[a-z']{3,}", it["text"].lower()) if w not in STOP]
        docs[k] = Counter(words)
    df = Counter(w for c in docs.values() for w in c)
    n = len(docs)
    vecs = {}
    for k, c in docs.items():
        v = {w: (1 + math.log(f)) * math.log(n / (1 + df[w])) for w, f in c.items() if df[w] > 1}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs[k] = {w: x / norm for w, x in v.items()}
    return vecs


async def _embeddings(lib: dict) -> dict | None:
    """Ollama plot vectors (cached in DATA_DIR) - None if Ollama isn't set up or doesn't answer."""
    if not config.OLLAMA_URL:
        return None
    cache = store.load("plot_vectors.json", {})
    todo = [(k, hashlib.sha1(it["text"].encode()).hexdigest()[:12]) for k, it in lib.items()
            if cache.get(k, {}).get("h") != hashlib.sha1(it["text"].encode()).hexdigest()[:12]]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
            for i in range(0, len(todo), 32):
                chunk = todo[i:i + 32]
                async with s.post(f"{config.OLLAMA_URL}/api/embed", json={
                        "model": config.EMBED_MODEL, "input": [f"search_document: {lib[k]['text']}" for k, _ in chunk]}) as r:
                    vecs = (await r.json())["embeddings"]
                for (k, h), v in zip(chunk, vecs):
                    norm = math.sqrt(sum(x * x for x in v)) or 1.0
                    cache[k] = {"h": h, "v": [round(x / norm, 5) for x in v]}
    except Exception as e:
        log.warning(f"Ollama embeddings unavailable ({e}) - using the built-in plot matcher")
        return None
    store.save("plot_vectors.json", {k: v for k, v in cache.items() if k in lib})
    return {k: v["v"] for k, v in cache.items() if k in lib}


def _sim(a, b) -> float:
    if isinstance(a, dict):                               # TF-IDF (sparse)
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(w, 0.0) for w, x in a.items())
    return sum(x * y for x, y in zip(a, b))              # embeddings (dense, unit length)


def _franchise(title: str) -> str:
    words = [w for w in re.split(r"[^a-z0-9]+", title.lower().split(":")[0]) if w and w not in _SMALL and not w.isdigit()]
    return " ".join(words[:2])


def _same(it: dict) -> str:
    return f"{it['type']}|{plex.norm(it['title'])}|{it['year']}"


async def _histories() -> dict:
    hist = (await plex.get("/status/sessions/history/all", {"sort": "viewedAt:desc"}, timeout=120) or {}).get("Metadata", [])
    out = {}
    for h in hist:
        key = h.get("grandparentRatingKey") if h.get("type") == "episode" else h.get("ratingKey")
        if key:
            rec = out.setdefault(str(h.get("accountID")), {"recent": [], "seen": set()})
            if str(key) not in rec["seen"]:
                rec["recent"].append(str(key))
            rec["seen"].add(str(key))
    return out


def _pick(hist: dict, vecs: dict, lib: dict) -> list:
    group = {k: _same(lib[k]) for k in vecs}
    seen_groups = {_same(lib[k]) for k in hist["seen"] if k in lib}
    watched, wg = [], set()
    for k in hist["recent"]:
        if k in vecs and group[k] not in wg:
            wg.add(group[k])
            watched.append(k)
    watched = watched[:HISTORY_TITLES]
    if len(watched) < 2:
        return []
    weights = [1.0 - 0.4 * i / max(1, len(watched) - 1) for i in range(len(watched))]
    scored = []
    for k, v in vecs.items():
        if group[k] in seen_groups:
            continue
        best, because = 0.0, None
        for w, wt in zip(watched, weights):
            s = _sim(v, vecs[w]) * wt
            if s > best:
                best, because = s, w
        if because:
            scored.append((best, k, because))
    scored.sort(reverse=True)
    franchises = {_franchise(lib[k]["title"]) for k in watched} - {""}
    picks, reasons, picked = [], set(), set()
    for score, k, because in scored:
        if len(picks) >= PER_PERSON:
            break
        fr = _franchise(lib[k]["title"])
        words = " " + " ".join(re.split(r"[^a-z0-9]+", lib[k]["title"].lower())) + " "
        if group[k] in picked or because in reasons or fr in franchises or \
                any(f" {f} " in words for f in franchises):      # "The Amazing Spider-Man" is still Spider-Man
            continue
        picked.add(group[k]), franchises.add(fr), reasons.add(because)
        it = lib[k]
        picks.append({"key": k, "type": "show" if it["type"] == "show" else "movie", "thumb": it["thumb"],
                      "title": it["title"] + (f" ({it['year']})" if it["type"] == "movie" and it["year"] else ""),
                      "year": it["year"], "why": f"Because you watched {lib[because]['title']}"})
    return picks


async def refresh() -> int:
    started = time.time()
    lib = await _library()
    if not lib:
        log.warning("Couldn't read the library - recommendations not refreshed")
        return 0
    vecs = await _embeddings(lib) or await asyncio.to_thread(_tfidf, lib)
    out = {}
    for acct, h in (await _histories()).items():
        picks = await asyncio.to_thread(_pick, h, vecs, lib)
        if picks:
            out[acct] = {"updated": int(time.time()), "items": picks}
    store.save(OUT, out)
    log.info(f"Recommendations for {len(out)} people ({len(lib)} titles) in {time.time() - started:.0f}s")
    return len(out)


def for_account(acct) -> list:
    return store.load(OUT, {}).get(str(acct), {}).get("items", [])


async def loop():
    await asyncio.sleep(90)
    while True:
        try:
            await refresh()
        except Exception:
            log.exception("Recommendations failed")
        now = datetime.now()
        wait = ((NIGHTLY_AT - now.hour) % 24 or 24) * 3600 - now.minute * 60 - now.second
        await asyncio.sleep(max(3600, wait))
