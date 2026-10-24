<p align="center">
  <img src="marquee/web/logo-256.png" width="140" alt="Marquee">
</p>

<h1 align="center">Marquee</h1>

<p align="center">
  <strong>The front-of-house for your Plex server.</strong><br>
  A beautiful, self-hosted app your friends and family open on their phones to browse what's on your server,
  request what isn't, and get recommendations picked just for them.
</p>

<p align="center">
  <em>Sign in with Plex · Real search · Requests with approvals · Personal recommendations · Who's watching · Push notifications</em>
</p>

---

## Why Marquee?

You run a Plex server. People text you *"do you have…?"*, *"can you add…?"*, *"what's new?"* — all day.

**Marquee answers all of that for you.** Share one link, and everyone who already has access to your server gets a gorgeous
app on their phone where they can see everything you have, ask for what you don't, and discover things they'll love —
while you approve requests with a single tap.

No new accounts. No passwords to hand out. If they can watch your Plex, they can sign in to Marquee.

## ✨ Features

### For everyone on your server
- **Sign in with Plex** — on Plex's own page. Marquee never sees anyone's password, and only accounts with access to
  *your* server get in.
- **A home screen worth opening** — new releases, recently added, and big poster art pulled straight from your server.
- **Picked for you** — personal recommendations from what *each person* actually watched. Matched on **plot and
  theme** (never actors, directors or title words), only titles already on your server, never something they've seen,
  one pick per franchise, each with a reason: *"Because you watched Arrival."*
- **Real search** — instant results from your library. Own a movie in 4K *and* HD, or in Theatrical *and* Extended?
  It shows up **once**, with every edition listed together.
- **Title pages** — plot, runtime, rating, every version you have, and a **Play on Plex** button.
- **Requests that just work** — search for anything; if it isn't on your server they pick the exact IMDb title and tap
  Request. Duplicates and titles you already have are caught automatically.
- **My requests** — see where every request stands (waiting → approved → ready), and cancel any time before it lands.
- **Notifications** — when a request is answered, when it's ready to watch, and a single tidy *"New arrivals"* alert
  when new movies, shows or seasons hit your server.
- **Report a problem** — right from the sign-in screen or inside the app.

### For you, the server owner
- **Approvals in one tap** — approve, or decline with a friendly ready-made message (or write your own).
- **Your requests are instant** — just type a name; yours are approved automatically.
- **Approved → Ready** — Marquee watches your library and tells people the moment their title arrives. Added it
  yourself? Tap **Mark complete**.
- **Who's watching** — live streams: who, what, how far in, which device, direct play or converting, bandwidth.
- **Members** — who's using Marquee, who's **online right now**, when everyone was last active, and who you've shared
  your server with that **hasn't joined yet**.
- **Alerts** — new requests, new members and problem reports as notifications on your phone (and optionally in Discord
  or Slack).

### Built right
- **Installs like a real app** on iPhone and Android (Add to Home Screen) — full-screen, with its own icon.
- **Private by design** — your Plex token stays on your server and is never sent to anyone's phone; posters are proxied
  through Marquee. Sessions are signed cookies. Nothing phones home.
- **Lightweight** — one small Python service, plain JSON files, no database to run.
- **Smarter with Ollama (optional)** — point Marquee at an Ollama server and recommendations use an AI model that
  understands plots. Without it, the built-in plot matcher works great and needs nothing extra.

---

## 🚀 Quick start

You'll need **Python 3.10+**, your **Plex server address**, and your **Plex token**.

```bash
git clone https://github.com/Dreamkeeper-afk/marquee.git
cd marquee
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in PLEX_URL, PLEX_TOKEN and PUBLIC_URL
python -m marquee
```

That's it — Marquee is running on `http://127.0.0.1:8484`. Next, make it reachable on `https://` (below) and share the link.

### Finding your Plex token

It takes about 20 seconds:

1. Open Plex in your web browser and sign in as the **server owner**.
2. Pick **any movie**, click the **⋯** (three dots) → **Get Info**.
3. Click **View XML** at the bottom. A new tab opens with a long address.
4. At the very end of that address is **`X-Plex-Token=`** followed by your token. Copy everything after the `=`.

Put it in `.env` as `PLEX_TOKEN=...`. Keep it secret — it's the key to your server.

> Want the official guide? Plex documents it here:
> [Finding an authentication token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)

### Making Marquee reachable (https)

Plex sign-in and phone notifications need a real `https://` address. Pick whichever you like:

| Option | Good for | How |
|---|---|---|
| **Tailscale Funnel** | Easiest, free, no router changes | `tailscale funnel --bg --https=443 http://127.0.0.1:8484` — your address is shown by `tailscale funnel status` |
| **Cloudflare Tunnel** | Your own domain, free | `cloudflared tunnel --url http://127.0.0.1:8484` (or a named tunnel to `marquee.yourdomain.com`) |
| **Reverse proxy** | You already run Caddy / Nginx / Traefik | Proxy your domain to `127.0.0.1:8484` with HTTPS |

Set `PUBLIC_URL` in `.env` to that address (e.g. `https://marquee.yourdomain.com`) and restart Marquee.

### Docker

```bash
cp .env.example .env    # fill it in
docker compose up -d
```

Data lives in `./data`. The container listens on port `8484`.

---

## ⚙️ Configuration

All settings go in `.env` (see `.env.example`):

| Setting | Required | What it does |
|---|---|---|
| `PLEX_URL` | Yes | Your Plex server, e.g. `http://192.168.1.20:32400` |
| `PLEX_TOKEN` | Yes | Your Plex token ([how to find it](#finding-your-plex-token)) |
| `PUBLIC_URL` | Yes | The `https://` address people open Marquee at |
| `PORT` | | Port to listen on (default `8484`) |
| `HOST` | | Address to listen on (default `127.0.0.1`; Docker uses `0.0.0.0`) |
| `DATA_DIR` | | Where Marquee keeps its data (default `./data`) |
| `REVIEW_TIME` | | How long requests usually take, shown to people (default `24-48 hours`) |
| `BLOCK_ANIME` | | `true` to automatically decline anime requests |
| `OLLAMA_URL` | | An Ollama server for AI plot matching, e.g. `http://localhost:11434` |
| `EMBED_MODEL` | | The Ollama embedding model (default `nomic-embed-text`) |
| `ALERT_WEBHOOK` | | A Discord or Slack webhook — your alerts are also posted there |

---

## 🧩 Optional extras

Marquee works on its own — no Discord, no other services. If you *want* to connect things, here are the options:

### Discord or Slack alerts (built in)
Get new requests, new members and problem reports posted to a channel:

- **Discord:** Server Settings → **Integrations** → **Webhooks** → **New Webhook** → pick a channel → **Copy Webhook URL**.
- **Slack:** create an **Incoming Webhook** in your Slack workspace and copy its URL.

Paste it into `.env` as `ALERT_WEBHOOK=...` and restart. (Phone notifications keep working too.)

### Other notification services
Anything that accepts a Discord- or Slack-style webhook works with `ALERT_WEBHOOK` — for example
[ntfy](https://ntfy.sh), [Gotify](https://gotify.net) (via a webhook bridge), or [Apprise](https://github.com/caronc/apprise)
to fan out to Telegram, email, Pushover and more.

### Smarter recommendations with Ollama
Install [Ollama](https://ollama.com), run `ollama pull nomic-embed-text`, and set `OLLAMA_URL`. Marquee will use it for
plot matching and fall back to the built-in matcher if it's ever unavailable. A GPU isn't required.

### A Discord bot for requests
Marquee doesn't need one — but if your community lives in Discord, you can run a request bot alongside it and keep
Marquee as the app. Point people to Marquee for browsing, recommendations and request status.

---

## 🔒 Privacy & security

- **Passwords never touch Marquee.** Sign-in happens on Plex's own website (`app.plex.tv`).
- **Only your people get in.** After sign-in, Marquee checks with Plex that the account has access to *your* server.
  Their Plex sign-in is used once for that check and then discarded.
- **Your Plex token stays put.** It lives in your `.env` on your machine; posters and art are fetched through Marquee so
  the token never reaches a phone.
- **You own the data.** Everything is plain JSON in `DATA_DIR`. Nothing is sent anywhere else.

> **Heads-up for your users:** when someone signs in, Plex may show a red *"Security Alert — another device is attempting
> to sign in"* or email them that *Marquee* signed in. That's Plex confirming the sign-in with your server, and it's safe
> to continue. Marquee's sign-in screen explains this (with a picture) so nobody is caught off guard.

---

## ❓ FAQ

**Does everyone need an account?** No. Anyone you've shared your Plex server with signs in with their existing Plex
account.

**Does it work away from home?** Yes — on Wi-Fi or cellular, anywhere, once it has an `https://` address.

**Can people see each other's requests?** No. Everyone sees only their own. You see all of them.

**Will recommendations spoil what I watched?** Each person's picks come from *their own* watch history, and only they
can see them.

**Does it change anything on my Plex server?** No. Marquee only reads from Plex. Requests are a list for you — you add the
titles your way.

---

## Running it as a service

- **Linux (systemd):** create `/etc/systemd/system/marquee.service` with `WorkingDirectory=/path/to/marquee` and
  `ExecStart=/path/to/marquee/.venv/bin/python -m marquee`, then `systemctl enable --now marquee`.
- **macOS:** a LaunchAgent running `.venv/bin/python -m marquee` in the project folder.
- **Windows:** a Task Scheduler task "At startup" running `.venv\Scripts\python.exe -m marquee`.
- **Docker:** `docker compose up -d` (restarts automatically).

---

## 🔄 Updating

New versions of Marquee are published as **[Releases](../../releases)** — update whenever it suits you. Your settings
(`.env`) and data (`DATA_DIR`) are never touched by an update.

```bash
cd marquee
git pull
source .venv/bin/activate && pip install -r requirements.txt
# then restart Marquee
```

With Docker: `git pull && docker compose up -d --build`.

---

## License

[MIT](LICENSE) — free to use, change and share.

<p align="center"><sub>Marquee is an independent project and isn't affiliated with or endorsed by Plex Inc.</sub></p>
