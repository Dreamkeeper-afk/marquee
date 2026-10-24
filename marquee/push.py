"""Phone notifications (Web Push). Works in Chrome/Android, and on iPhone once Marquee is added to the Home Screen."""
import json
import base64
import asyncio
import logging

from . import config, store

log = logging.getLogger("marquee.push")
SUBS = "push_subscriptions.json"                         # {plex user id: [subscriptions]}


def _keys() -> dict:
    def make():
        from py_vapid import Vapid
        from cryptography.hazmat.primitives import serialization
        v = Vapid()
        v.generate_keys()
        raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return json.dumps({"private": v.private_pem().decode(), "public": base64.urlsafe_b64encode(raw).decode().rstrip("=")})
    return json.loads(store.secret("vapid.json", make))


def public_key() -> str:
    return _keys()["public"]


def subscribe(user_id, sub: dict):
    subs = store.load(SUBS, {})
    uid = str(user_id)
    subs[uid] = [s for s in subs.get(uid, []) if s.get("endpoint") != sub.get("endpoint")] + [sub]
    store.save(SUBS, subs)


def subscribed() -> list[str]:
    return [u for u, s in store.load(SUBS, {}).items() if s]


def _send(user_ids, title: str, body: str, page: str) -> int:
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    subs, sent, changed = store.load(SUBS, {}), 0, False
    vapid = Vapid.from_pem(_keys()["private"].encode())
    for uid in [str(u) for u in user_ids]:
        keep = []
        for s in subs.get(uid, []):
            try:
                webpush(s, json.dumps({"title": title, "body": body, "page": page}), vapid_private_key=vapid,
                        vapid_claims={"sub": config.PUBLIC_URL or "mailto:marquee@localhost"}, timeout=5, ttl=86400)
                sent += 1
                keep.append(s)
            except WebPushException as e:
                if getattr(e.response, "status_code", 0) in (404, 410):
                    changed = True                       # they turned notifications off / removed the app
                else:
                    keep.append(s)
            except Exception:
                keep.append(s)
        if uid in subs:
            subs[uid] = keep
    if changed:
        store.save(SUBS, subs)
    return sent


async def send(user_ids, title: str, body: str, page: str = "home") -> int:
    return await asyncio.get_running_loop().run_in_executor(None, _send, list(user_ids), title, body, page)


def send_soon(user_ids, title: str, body: str, page: str = "home"):
    asyncio.get_running_loop().run_in_executor(None, _send, list(user_ids), title, body, page)


async def owner_alert(title: str, body: str, page: str = "home"):
    """An alert for the server owner: a notification, and the optional ALERT_WEBHOOK (Discord/Slack)."""
    from . import plex
    srv = await plex.server()
    send_soon([srv.get("owner_id")], title, body, page)
    if config.ALERT_WEBHOOK:
        import aiohttp
        text = f"**{title}**\n{body}"
        payload = {"content": text, "allowed_mentions": {"parse": []}} if "discord" in config.ALERT_WEBHOOK else {"text": text}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                await s.post(config.ALERT_WEBHOOK, json=payload)
        except Exception as e:
            log.info(f"Alert webhook: {e}")
