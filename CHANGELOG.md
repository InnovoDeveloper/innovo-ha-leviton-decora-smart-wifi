# Changelog

All notable changes in this Innovo fork. Upstream releases by [@schmittx](https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi) are noted where this fork rebases onto them.

## [2026.9.1] - 2026-09-05 (Innovo fork, based on upstream 2.1.3)

Rebased onto upstream `2.1.3`, which now includes the cloud websocket push and
`event` platform originally developed in this fork (upstream PR #25). Those are
no longer fork-specific.

### Fixed
- **Automatic token renewal never fired.** Recovery from an expired bearer was gated on the API returning the exact string `"Invalid Access Token"`; Leviton answers with `"Authorization Required"`, so the integration never re-authenticated and stayed 401ing indefinitely. Recovery is now keyed off the 401 status itself.
- **Re-login could not have worked even if the gate had matched** — the API object is constructed from the stored token alone, leaving `credentials` empty, so the re-login path would have raised `KeyError: 'email'`.
- **The retry after a re-login replayed the dead token**, because the auth header was built before re-authentication ran. The header is now rebuilt per attempt.
- **A failed first fetch killed the config entry permanently.** Setup called `coordinator.async_refresh()`, which swallows fetch errors and leaves `.data` as `None`, then immediately dereferenced `coordinator.data.residences` — raising `AttributeError`. An unhandled exception puts the entry in `SETUP_ERROR`, which Home Assistant never retries, so a transient network problem at startup (typically a DNS blip while the network is still coming up at boot) left the integration dead until someone restarted by hand. Setup now uses `async_config_entry_first_refresh()` and raises `ConfigEntryNotReady`, entering the automatic backoff retry.

### Added
- **`api/throttle.py` — a shared login throttle.** Every automatic re-login, from both the REST poller and the websocket client, passes through it: 60s minimum spacing, exponential failure backoff (60s → 1h), a 1h cooldown on `403 Too many failed attempts`, and a hard ceiling of 5 logins per rolling hour. Verified against a simulated week of once-per-second login attempts across four failure modes (always-fails, locked-out, always-succeeds, flapping); the rolling-hour ceiling held in every one, with a worst sustained rate of ~25 logins/day.
- **Refreshed tokens are persisted** to the config entry, including the full login response.

### Changed
- `async_update_listener` now compares options against a snapshot, so writing a refreshed token no longer reloads the config entry. That reload-on-token-write was the mechanism behind a previous login storm.
- `codeowners`, `documentation` and `issue_tracker` point at this fork; the integration `domain` and display name are unchanged, so upgrading in place preserves existing config entries, entity IDs and history.

## [1.8.0] - 2026-04-29 (Innovo fork)
### Added
- **Cloud websocket push** (`api/websocket.py`) — async aiohttp client to `wss://my.leviton.com/socket/websocket`, persistent connection, native subscribe/notification protocol, 30 s ping keepalive.
- **Event platform** (`event.py`) — one `event` entity per scene-controller button. Fires `press` event with `trigger`, `button`, `rssi`, `lastUpdated` attributes when the cloud reports a physical press.
- **Full login response persistence** — config flow now stores the entire `POST /Person/login?include=user` response in `CONF_LOGIN_RESPONSE`; the websocket reuses it across reconnects without re-authenticating.

### Changed
- `iot_class` upgraded from `cloud_polling` to `cloud_push`.
- Websocket reconnect/back-off is conservative: linear-then-capped backoff for transient errors (30 s → 600 s) and a 1-hour cooldown on auth-rejected to prevent Leviton's "too many failed attempts" account lockout.
- `LevitonAPI.refresh()` now retries once with a fresh `requests.Session` on `ConnectionError` (recovers from Leviton's stale keep-alive drops without flipping every entity to `unavailable`).

### Notes
- Leviton's cloud only emits `btnPress` notifications for buttons that are bound to at least one action in the MyLeviton mobile app. Buttons with no action remain silent — bind a placeholder scene to expose them in HA.
- Subscribes only to `IotSwitch` per configured device; physical presses arrive on the parent IotSwitch as `data.btnPress: [{button: N, trigger: T}]`. There is no separate `IotButton` push channel.
