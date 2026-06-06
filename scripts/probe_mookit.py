"""Live mooKIT connectivity probe — run on a network that can reach test.mookit.in.

Verifies the real MooKitClient against the live test instance using the dev headers. Reads:
  - GET /users/me
  - GET /user_permissions/allowed
  - GET /taxonomies/week

Usage:
    MOOKIT_TOKEN=<full-jwt> python scripts/probe_mookit.py
    # base url + course/uid can be overridden via env (see below)

NOTE: the token in docs/details.md appears truncated; supply a full JWT via MOOKIT_TOKEN.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import RequestContext  # noqa: E402
from app.mookit.client import MooKitClient  # noqa: E402

BASE_URL = os.getenv("MOOKIT_BASE_URL", "https://test.mookit.in/api")
COURSE = os.getenv("MOOKIT_COURSE", "coursetest")
UID = os.getenv("MOOKIT_UID", "1")
TOKEN = os.getenv("MOOKIT_TOKEN", "")


async def main() -> None:
    if not TOKEN:
        print("WARNING: no MOOKIT_TOKEN set — requests will likely 401. Set a full JWT.")
    async with httpx.AsyncClient(http2=True, timeout=15) as http:
        client = MooKitClient(http=http, base_url_resolver=lambda _id: BASE_URL)
        ctx = RequestContext(
            instance_id="test.mookit.in",
            course_id=COURSE,
            user_id=int(UID),
            session_id="probe",
            forwarded_headers={"course": COURSE, "token": TOKEN, "uid": UID},
        )
        for label, coro in [
            ("users_me", client.users_me(ctx)),
            ("get_permissions", client.get_permissions(ctx)),
            ("list_taxonomy(week)", client.list_taxonomy(ctx, "week")),
        ]:
            try:
                result = await coro
                print(f"OK  {label}: {result}")
            except Exception as exc:  # noqa: BLE001
                print(f"ERR {label}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
