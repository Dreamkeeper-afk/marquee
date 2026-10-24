"""Run Marquee:  python -m marquee"""
import sys
import logging

from aiohttp import web

from . import config


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    missing = config.problems()
    if missing:
        print("Marquee isn't set up yet:\n  - " + "\n  - ".join(missing) + "\nSee README.md (Quick start).")
        sys.exit(1)
    from .server import build
    print(f"🎬 Marquee is running on http://{config.HOST}:{config.PORT}  (people open it at {config.PUBLIC_URL})")
    web.run_app(build(), host=config.HOST, port=config.PORT, print=None)


if __name__ == "__main__":
    main()
