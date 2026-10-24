"""IMDb title matches for requests, plus an optional anime check (BLOCK_ANIME)."""
import re
import logging
import urllib.parse

import aiohttp

log = logging.getLogger("marquee.imdb")
IMDB_ID = re.compile(r"tt\d{7,9}")
KINDS = {"feature": "movie", "TV series": "TV series", "TV mini-series": "mini-series", "TV movie": "TV movie",
         "TV special": "TV special"}
ANIME_QIDS = {"Q1107", "Q63952888", "Q20650540"}       # Wikidata: anime, anime television series, anime film


async def candidates(query: str, limit: int = 5) -> list[dict]:
    """Real IMDb titles for a typed name (IMDb's own search suggestions): [{id, title, year, kind, url}]."""
    url = f"https://v3.sg.media-imdb.com/suggestion/x/{urllib.parse.quote(query.strip().lower())}.json"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
                found = (await r.json(content_type=None)).get("d", [])
    except Exception as e:
        log.info(f"IMDb suggestions: {e}")
        return []
    out = []
    for x in found:
        kind = KINDS.get(x.get("q") or x.get("qid"))
        if x.get("id", "").startswith("tt") and kind:
            out.append({"id": x["id"], "title": x.get("l", query), "year": x.get("y"), "kind": kind,
                        "url": f"https://www.imdb.com/title/{x['id']}/"})
        if len(out) >= limit:
            break
    return out


async def _anilist_says_anime(name: str) -> bool:
    year = re.search(r"\b(19|20)\d{2}\b", name)
    year = int(year.group(0)) if year else None
    wanted = re.sub(r"[^a-z0-9]+", " ", re.sub(r"[(\[]?\b(19|20)\d{2}\b[)\]]?", "", name).lower()).strip()
    if not wanted:
        return False
    q = """query($s:String){Page(perPage:10){media(search:$s,type:ANIME){
      title{romaji english native} synonyms seasonYear startDate{year}}}}"""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
            async with s.post("https://graphql.anilist.co", json={"query": q, "variables": {"s": wanted}}) as r:
                media = (await r.json(content_type=None))["data"]["Page"]["media"]
    except Exception:
        return False
    for m in media:
        names = {m["title"].get("romaji"), m["title"].get("english"), *m.get("synonyms", [])}
        aired = m.get("seasonYear") or (m.get("startDate") or {}).get("year")
        norm = {re.sub(r"[^a-z0-9]+", " ", n.lower()).strip() for n in names if n}
        if wanted in norm and (year is None or aired == year):
            return True
    return False


async def is_anime(imdb_id: str, title: str) -> bool:
    """Wikidata's genre for the IMDb id, then AniList by name. Unknown = not anime."""
    query = ("SELECT (GROUP_CONCAT(DISTINCT ?c;separator=',') AS ?classes) WHERE { "
             f'?item wdt:P345 "{imdb_id}" . OPTIONAL {{ ?item wdt:P136|wdt:P31 ?c }} }}')
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get("https://query.wikidata.org/sparql", params={"query": query},
                             headers={"Accept": "application/sparql-results+json", "User-Agent": "Marquee/1.0"}) as r:
                rows = (await r.json(content_type=None))["results"]["bindings"]
        classes = {c.rsplit("/", 1)[-1] for c in (rows[0].get("classes", {}).get("value", "") if rows else "").split(",") if c}
        if classes & ANIME_QIDS:
            return True
    except Exception:
        pass
    return await _anilist_says_anime(title)
