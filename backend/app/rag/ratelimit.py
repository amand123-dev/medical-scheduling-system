"""
A per-user cap on generation calls.

This is defence in depth, not the real control. The deployed demo is public and
its seeded credentials are in a public repo, so anything reachable that costs
money per request needs *some* brake. The brake that actually caps spend is the
spend limit configured with the model provider; this only stops one account
looping.

Deliberately in-process: no Redis, no extra dependency for a portfolio
deployment. The honest consequence is that the limit is per machine, so a
two-machine deployment allows up to twice the configured rate, and the counters
reset whenever a machine restarts or wakes from sleep. That is an acceptable
trade for a demo and an unacceptable one for anything metered in production,
where this belongs in shared storage.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

# user id -> timestamps of recent calls, oldest first
_calls: dict[str, deque[float]] = defaultdict(deque)


def check(user_id: str, limit: int, window_seconds: int = 3600) -> int | None:
    """
    Record a call and return None if allowed.

    When the limit is exceeded, returns the seconds until the oldest call ages
    out -- suitable for a Retry-After header -- and does NOT record the call, so
    a client hammering a closed door cannot push its own reset further away.
    """
    if limit <= 0:
        return None

    now = time.monotonic()
    recent = _calls[user_id]
    cutoff = now - window_seconds
    while recent and recent[0] < cutoff:
        recent.popleft()

    if len(recent) >= limit:
        return max(1, int(recent[0] + window_seconds - now))

    recent.append(now)
    return None


def reset() -> None:
    """Clear all counters. For tests."""
    _calls.clear()
