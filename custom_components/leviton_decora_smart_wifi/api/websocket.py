"""Leviton API.

Connects to ``wss://my.leviton.com/socket/websocket`` and subscribes to
real-time push notifications. The protocol was reverse-engineered from
the official myapp.leviton.com bundle (``authenticateSocketConnection``
wired to ``onOpen``) and the homebridge-myleviton plugin.

Auth model used here:
- We never call ``LevitonAPI.login`` directly. The bearer token already
  in the config entry is enough to synthesize a token payload.
- If auth fails, we ask the owning integration for a refreshed token via
  ``token_refresher``. That path is rate limited by the shared
  ``LoginThrottle``, so a permanently bad credential set can only ever
  produce a handful of login calls per hour.
- If no fresh token is forthcoming, we back off ``AUTH_FAILURE_COOLDOWN``
  (default 1 hour) before retrying, so we never hammer Leviton's auth
  endpoint and lock the account out.
"""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import json
import logging
import random
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

WS_URL = "wss://my.leviton.com/socket/websocket"
WS_ORIGIN = "https://my.leviton.com"

PING_INTERVAL = 30.0

# Reconnect backoff after the socket drops. Connecting never logs in (auth
# failures take the separate, throttled path below), so retrying quickly is
# safe. While the socket is down, paddle changes reach Home Assistant only
# through the slow poll and keypad presses are lost outright, so the gap is
# kept short: 5s first, doubling to a 2 minute ceiling, with jitter so many
# installs do not reconnect in lockstep after a cloud outage.
INITIAL_RECONNECT_DELAY = 5.0
MAX_RECONNECT_DELAY = 120.0
RECONNECT_JITTER = 0.2

# A reconnect after an outage at least this long is logged as a warning, so
# outages are visible in a default (warning level) log.
OUTAGE_REPORT_THRESHOLD = 60.0

# Auth failure cooldown — long, so we never hammer Leviton even if the
# token is bad. The integration's polling layer continues to work.
AUTH_FAILURE_COOLDOWN = 3600.0

# Short pause after a successful token refresh before reconnecting, so a
# server-side rejection loop still cannot spin.
POST_REFRESH_DELAY = 5.0

CHALLENGE_TIMEOUT = 10.0

# Subscription watchdog.
#
# The failure this guards against is a socket that stays open and keeps
# answering pings while the server has quietly forgotten our subscriptions:
# aiohttp's heartbeat cannot see it, so without this the integration goes
# permanently deaf while looking healthy.
#
# Note this is deliberately NOT ldata-ha's "no data for 60s -> resubscribe".
# That works for an energy monitor, which streams continuously, but a Decora
# account is legitimately silent for hours -- the cloud only pushes on change
# -- so silence is not evidence of anything and must never by itself force a
# reconnect. Instead the (idempotent) subscribe frames are simply re-sent on a
# slow timer, which costs one small frame per device and repairs dropped
# subscriptions whether or not anything was wrong.
RESUBSCRIBE_INTERVAL = 900.0

# Only after this many consecutive silent re-subscribes is the socket assumed
# wedged and torn down for a fresh connect. At the default interval that is a
# little over an hour of total silence. Any inbound notification resets it.
MAX_SILENT_RESUBSCRIBES = 4


class LevitonWebSocket:
    """Persistent WebSocket subscriber for the MyLeviton cloud."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token_provider: Callable[[], dict[str, Any] | None],
        on_notification: Callable[[dict[str, Any]], None],
        token_refresher: Callable[[], Awaitable[bool]] | None = None,
        on_connection_change: Callable[[bool, bool], None] | None = None,
    ) -> None:
        """Initialize.

        ``on_connection_change(connected, reconnect)`` is called when the
        socket becomes usable (authenticated and subscribed) and when it is
        lost. ``reconnect`` is True when a connection follows an earlier one,
        meaning pushes may have been missed in between.
        """
        self._session = session
        self._token_provider = token_provider
        self._on_notification = on_notification
        self._token_refresher = token_refresher
        self._on_connection_change = on_connection_change
        self._subscriptions: list[tuple[str, int]] = []
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._connected = False
        self._ever_connected = False
        self._down_since: float | None = None
        self._outage_logged = False

    @property
    def connected(self) -> bool:
        """Return True while the socket is authenticated and subscribed."""
        return self._connected

    def _notify_connection_change(self, connected: bool, reconnect: bool) -> None:
        if self._on_connection_change is None:
            return
        try:
            self._on_connection_change(connected, reconnect)
        except Exception:
            _LOGGER.exception("Leviton WebSocket connection callback raised")

    def _mark_connected(self) -> None:
        loop = asyncio.get_running_loop()
        downtime = loop.time() - self._down_since if self._down_since else None
        long_outage = downtime is not None and downtime >= OUTAGE_REPORT_THRESHOLD
        # A first connection that only succeeded after a long outage can also
        # have missed changes since setup's initial fetch.
        reconnect = self._ever_connected or long_outage
        if long_outage:
            _LOGGER.warning(
                "Leviton push reconnected after %dm%02ds; refreshing device state",
                downtime // 60,
                downtime % 60,
            )
        elif reconnect:
            _LOGGER.info("Leviton push reconnected; refreshing device state")
        self._connected = True
        self._ever_connected = True
        self._down_since = None
        self._outage_logged = False
        self._notify_connection_change(True, reconnect)

    def _mark_disconnected(self) -> None:
        self._connected = False
        self._down_since = asyncio.get_running_loop().time()
        _LOGGER.info("Leviton push disconnected; reconnecting")
        self._notify_connection_change(False, False)

    def set_subscriptions(self, subs: list[tuple[str, int]]) -> None:
        """Replace the subscription set; takes effect on next connect."""
        self._subscriptions = list(subs)
        if self._ready.is_set() and self._ws is not None and not self._ws.closed:
            self._task = asyncio.create_task(self._send_subscriptions())

    def start(self) -> None:
        """Start the WebSocket loop as a background task."""
        if self._task and not self._task.done():
            return
        self._stop.clear()
        _LOGGER.debug("Leviton WebSocket task starting")
        self._task = asyncio.create_task(self._run(), name="leviton_ws")

    async def stop(self) -> None:
        """Stop the WebSocket loop and close the connection."""
        self._stop.set()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def _run(self) -> None:
        delay = INITIAL_RECONNECT_DELAY
        while not self._stop.is_set():
            token = self._token_provider()
            if not token or "id" not in token:
                if await self._async_refresh_token():
                    continue
                _LOGGER.error(
                    "Leviton WebSocket: no token available; sleeping for %.0fs",
                    AUTH_FAILURE_COOLDOWN,
                )
                await self._sleep_or_stop(AUTH_FAILURE_COOLDOWN)
                continue

            outcome = "transient"
            try:
                outcome = await self._connect(token)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Leviton WebSocket loop error")
            finally:
                self._ready.clear()
                self._ws = None
                if self._connected:
                    self._mark_disconnected()

            if outcome == "auth_failed":
                # The usual cause is an expired bearer. Ask for a fresh
                # one; the throttle behind this decides whether a login
                # is actually permitted right now.
                if await self._async_refresh_token():
                    _LOGGER.info(
                        "Leviton WebSocket: token refreshed, reconnecting"
                    )
                    await self._sleep_or_stop(POST_REFRESH_DELAY)
                    delay = INITIAL_RECONNECT_DELAY
                    continue
                _LOGGER.warning(
                    "Leviton WebSocket auth failed and no fresh token is available; "
                    "cooling down for %.0fs to avoid account lockout",
                    AUTH_FAILURE_COOLDOWN,
                )
                await self._sleep_or_stop(AUTH_FAILURE_COOLDOWN)
                delay = INITIAL_RECONNECT_DELAY
                continue

            if outcome == "ok":
                delay = INITIAL_RECONNECT_DELAY

            if not self._stop.is_set():
                jitter = random.uniform(1 - RECONNECT_JITTER, 1 + RECONNECT_JITTER)
                await self._sleep_or_stop(delay * jitter)
                delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _async_refresh_token(self) -> bool:
        """Ask the integration to renew the bearer token.

        Returns True only when a genuinely new token was obtained. The
        rate limiting lives in the refresher itself, so returning False
        here means "not now" and the caller must back off.
        """
        if self._token_refresher is None:
            return False
        try:
            return await self._token_refresher()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Leviton WebSocket token refresh raised")
            return False

    async def _sleep_or_stop(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    async def _connect(self, token: dict[str, Any]) -> str:
        """Open the WS, authenticate, then run the receive loop.

        Returns ``"ok"`` if we authenticated and ran cleanly,
        ``"auth_failed"`` if auth was rejected (so the caller backs off
        hard), or ``"transient"`` for any other failure.
        """
        _LOGGER.debug("Connecting to Leviton WebSocket %s", WS_URL)
        headers = {"Origin": WS_ORIGIN}
        try:
            async with self._session.ws_connect(
                WS_URL, headers=headers, heartbeat=PING_INTERVAL, autoclose=True
            ) as ws:
                self._ws = ws
                auth_outcome = await self._authenticate(ws, token)
                if auth_outcome != "ok":
                    return auth_outcome
                self._ready.set()
                await self._send_subscriptions()
                self._mark_connected()
                await self._receive_loop(ws)
                return "ok"
        except aiohttp.ClientError as err:
            # Once per outage at warning level; the retries that follow every
            # few seconds would otherwise flood the log for its duration.
            if self._outage_logged:
                _LOGGER.debug("Leviton WebSocket connection error: %s", err)
            else:
                self._outage_logged = True
                _LOGGER.warning(
                    "Leviton push connection failed (%s); retrying in the background",
                    err,
                )
            if self._down_since is None:
                self._down_since = asyncio.get_running_loop().time()
            return "transient"

    async def _authenticate(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        token: dict[str, Any],
    ) -> str:
        """Authenticate the WebSocket.

        Sends ``{token: <login response>}`` immediately on open per the
        myapp.leviton.com client behavior. Waits up to a short window for
        ``{type:"status", status:"ready"}``. Anything else (including the
        ``challenge`` frame with a nonce or repeated ``status:"not ready"``)
        is treated as info-level traffic and ignored — only an explicit
        rejection or timeout drops auth to ``auth_failed``.
        """
        await ws.send_json({"token": token})
        deadline = asyncio.get_running_loop().time() + CHALLENGE_TIMEOUT * 2

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                _LOGGER.error("WebSocket auth handshake timed out")
                return "auth_failed"

            try:
                frame = await asyncio.wait_for(ws.receive(), timeout=remaining)
            except TimeoutError:
                _LOGGER.error("WebSocket auth handshake timed out")
                return "auth_failed"

            if frame.type is aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(frame.data)
                except ValueError:
                    _LOGGER.warning("Non-JSON handshake frame: %r", frame.data)
                    continue
                _LOGGER.debug("WebSocket handshake frame: %s", payload)
                if payload.get("type") == "status" and payload.get("status") == "ready":
                    _LOGGER.info("Leviton WebSocket authenticated")
                    return "ok"
                continue

            if frame.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                _LOGGER.error(
                    "WebSocket closed during auth (code=%s)",
                    getattr(frame, "data", None),
                )
                return "auth_failed"
            if frame.type is aiohttp.WSMsgType.ERROR:
                _LOGGER.error("WebSocket error during auth: %s", ws.exception())
                return "auth_failed"

    async def _send_subscriptions(self) -> None:
        if self._ws is None or self._ws.closed:
            return
        for model_name, model_id in self._subscriptions:
            msg = {
                "type": "subscribe",
                "subscription": {"modelName": model_name, "modelId": model_id},
            }
            _LOGGER.debug("WebSocket subscribe: %s", msg)
            await self._ws.send_json(msg)

    async def _receive_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Pump inbound frames, re-subscribing if the socket goes quiet.

        Returning hands control back to ``_run``, which reconnects.
        """
        loop = asyncio.get_running_loop()
        last_traffic = loop.time()
        silent_resubscribes = 0

        while not self._stop.is_set():
            remaining = RESUBSCRIBE_INTERVAL - (loop.time() - last_traffic)

            if remaining <= 0:
                if silent_resubscribes >= MAX_SILENT_RESUBSCRIBES:
                    _LOGGER.debug(
                        "WebSocket silent after %d re-subscribes, reconnecting",
                        silent_resubscribes,
                    )
                    return
                silent_resubscribes += 1
                _LOGGER.debug(
                    "WebSocket quiet for %.0fs, re-subscribing (#%d)",
                    RESUBSCRIBE_INTERVAL,
                    silent_resubscribes,
                )
                try:
                    await self._send_subscriptions()
                except (aiohttp.ClientError, ConnectionResetError) as err:
                    _LOGGER.debug("WebSocket re-subscribe failed: %s", err)
                    return
                # Restart the window whether or not the server answers, so a
                # silent socket re-subscribes at a fixed slow cadence rather
                # than spinning.
                last_traffic = loop.time()
                continue

            try:
                msg = await ws.receive(timeout=remaining)
            except (TimeoutError, asyncio.TimeoutError):
                # Window elapsed with no frame; next iteration re-subscribes.
                continue

            if self._stop.is_set():
                break

            if msg.type is aiohttp.WSMsgType.TEXT:
                # Real payload: the subscriptions are demonstrably alive.
                last_traffic = loop.time()
                silent_resubscribes = 0
                self._dispatch(msg.data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                _LOGGER.debug("WebSocket closed/closing")
                break
            elif msg.type is aiohttp.WSMsgType.ERROR:
                _LOGGER.warning("WebSocket error: %s", ws.exception())
                break
            # PING/PONG/BINARY prove only that the transport is up, not that
            # the subscriptions are, so they deliberately do not reset the
            # watchdog.

    def _dispatch(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except ValueError:
            _LOGGER.warning("Non-JSON WS frame: %r", raw[:200])
            return

        msg_type = payload.get("type")
        if msg_type == "notification":
            _LOGGER.debug(
                "WebSocket notification: %s", json.dumps(payload, sort_keys=True)
            )
            try:
                self._on_notification(payload.get("notification") or {})
            except Exception:
                _LOGGER.exception("Notification handler raised")
        else:
            _LOGGER.debug("WebSocket frame (type=%s): %s", msg_type, payload)
