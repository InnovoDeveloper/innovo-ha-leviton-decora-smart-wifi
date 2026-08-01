"""Leviton API.

Rate limiting for ``POST /api/Person/login``.

Leviton locks an account out with ``403 Too many failed attempts`` once
too many logins are attempted in a short window, so every automatic
re-authentication in this integration goes through a single shared
``LoginThrottle``. The REST polling layer and the WebSocket client both
consult the same instance, which means a token that has gone bad can
only ever produce one login attempt, not one per subsystem.
"""

from collections import deque
from collections.abc import Callable
import logging
import threading
import time

_LOGGER = logging.getLogger(__name__)

# Never issue two login calls closer together than this, however many
# callers ask for one.
MIN_LOGIN_INTERVAL = 60.0

# Consecutive-failure backoff: 60s, 120s, 240s ... up to the cap.
FAILURE_BACKOFF_BASE = 60.0
FAILURE_BACKOFF_MAX = 3600.0

# Applied when Leviton reports the account is already locked out. The
# lockout has been observed to clear inside an hour; wait it out rather
# than confirming it with more traffic.
LOCKOUT_COOLDOWN = 3600.0

# Belt and braces: a hard ceiling on login calls in a rolling window, so
# that a bug anywhere else still cannot storm the endpoint.
ATTEMPT_WINDOW = 3600.0
MAX_ATTEMPTS_PER_WINDOW = 5


class LoginThrottle:
    """Gate on ``/Person/login`` shared by every automatic auth path.

    Thread safe: the REST layer calls in from executor threads while the
    WebSocket client calls in from the event loop.
    """

    def __init__(self, time_source: Callable[[], float] = time.monotonic) -> None:
        """Initialize."""
        self._now = time_source
        self._lock = threading.RLock()
        self._attempts: deque[float] = deque()
        self._last_attempt: float | None = None
        self._blocked_until: float = 0.0
        self._consecutive_failures: int = 0

    def retry_after(self) -> float:
        """Return seconds until a login is permitted, 0.0 if permitted now."""
        with self._lock:
            return self._retry_after()

    def acquire(self) -> bool:
        """Claim a login slot, returning False when rate limited.

        The attempt is recorded as soon as it is granted so that two
        callers racing for the same slot cannot both win it.
        """
        with self._lock:
            if self._retry_after() > 0.0:
                return False
            now = self._now()
            self._last_attempt = now
            self._attempts.append(now)
            return True

    def record_success(self) -> None:
        """Clear the failure backoff after a login succeeds."""
        with self._lock:
            self._consecutive_failures = 0
            self._blocked_until = 0.0

    def record_failure(self, locked_out: bool = False) -> None:
        """Extend the backoff after a login fails.

        ``locked_out`` marks the ``403 Too many failed attempts`` case,
        which jumps straight to the long cooldown instead of climbing
        the backoff ladder.
        """
        with self._lock:
            now = self._now()
            if locked_out:
                self._consecutive_failures += 1
                self._blocked_until = max(
                    self._blocked_until, now + LOCKOUT_COOLDOWN
                )
                _LOGGER.warning(
                    "Leviton reports the account is locked out; no further login "
                    "attempts for %.0fs",
                    LOCKOUT_COOLDOWN,
                )
                return
            self._consecutive_failures += 1
            delay = min(
                FAILURE_BACKOFF_BASE * 2 ** (self._consecutive_failures - 1),
                FAILURE_BACKOFF_MAX,
            )
            self._blocked_until = max(self._blocked_until, now + delay)

    def _retry_after(self) -> float:
        """Return seconds until a login is permitted. Caller holds the lock."""
        now = self._now()
        self._prune(now)

        waits = [self._blocked_until - now]
        if self._last_attempt is not None:
            waits.append(self._last_attempt + MIN_LOGIN_INTERVAL - now)
        if len(self._attempts) >= MAX_ATTEMPTS_PER_WINDOW:
            waits.append(self._attempts[0] + ATTEMPT_WINDOW - now)

        return max(0.0, max(waits))

    def _prune(self, now: float) -> None:
        """Drop attempts that have aged out of the rolling window."""
        cutoff = now - ATTEMPT_WINDOW
        while self._attempts and self._attempts[0] <= cutoff:
            self._attempts.popleft()
