"""Canonical payload hashing — binds the confirm token to (action, target, content).

The same scheme must be used by the publish tools (when proposing) and Dev A's gate (when confirming):
re-drafting changes the hash and voids the token (prevents "approve benign, swap malicious").
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
