# Changelog

All notable changes in this Innovo fork. Upstream releases by [@schmittx](https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi) are noted where this fork rebases onto them.

## [2026.10.2] - Unreleased (Innovo fork, based on upstream 2.1.3)

Folds in the unreleased 2026.9.2 and 2026.10.1 work and ports the useful parts of upstream 2.2.0–2.2.2. The minimum Home Assistant version stays 2026.6.0: upstream 2.2.x needs 2026.8 (`via_device_id`) and 2.2.2 needs 2026.9 (`probatio`), which this fork deliberately does not require.

### Fixed
- **A device command sent while Leviton was unreachable was lost.** During a DNS or internet outage, a scheduled "off" failed once and was dropped, leaving a light on all night. Device commands that fail because Leviton cannot be reached are now queued and retried every 15 seconds for up to 10 minutes. A newer command for the same device replaces the queued one, a command that later gets through cancels it, and every late delivery or give-up is logged.
- **After the real-time push connection dropped, paddle changes could stay invisible for up to the full polling interval (10 minutes by default).** The integration now fetches the current state as soon as the push connection is back, and reconnects faster: 5 seconds first, backing off to at most 2 minutes (was 30 seconds to 10 minutes).
- **One failed poll made every entity unavailable,** and a network error during a poll was logged as "Unexpected error fetching … data" with a traceback. The last known state is now kept for up to 2 consecutive failed polls, and network errors are reported as ordinary update failures. (From upstream 2.2.0.)
- **A hung request could stall the whole update.** Every request now has a 5 second connect and 10 second read timeout, and a timeout is retried once like a dropped connection. (From upstream 2.2.0.)
- **An HTML or empty answer from Leviton raised `JSONDecodeError`.** Such answers are retried once and then reported as a normal Leviton error. (From upstream 2.2.0.)
- **"Detected that custom integration … calls `device_registry.async_get_or_create` with a deprecated `via_device`" warnings** on Home Assistant 2026.8 and later. Devices are linked to their residence with `via_device_id` where Home Assistant supports it, and with `via_device` on older versions.
- **The physical paddle could not turn a light off after it was set to the brightness it already had.** Every level change sent `{"power": "ON", "brightness": <level>}`, even when the switch was already holding that level (e.g. 50% → off → 50%). After that request the switch turns the load straight back on whenever the paddle turns it off. A level equal to the stored one now sends power ON only; the switch restores the same level by itself.
- **Brightness lost 1% on about half of all levels** (e.g. 33%, 66%, 75%) because both conversions between Home Assistant's 0–255 scale and Leviton's 0–100 scale truncated. Both now round, which is exact for every level 1–100, so NICE/ELAN sees the level it set and a repeated level matches the stored one.
- **The push connection could go silently deaf:** the socket stayed open and answered pings while the cloud had dropped its subscriptions. Subscriptions are now re-sent every 15 minutes of silence, and the socket is rebuilt after about an hour with no notifications.

### Added
- **"Expose switches as lights" option** for installs migrating from Home Assistant's built-in `decora_wifi` integration, which modelled every device as a light. *Off* (default) keeps switches as switch entities; *Only switches whose name mentions "light"*; or *All switches*. Existing ELAN/Control4 bindings to `light.*` entity IDs survive the move.
- **Device support:** D36HD, D2710 and D315S (3rd generation, as classified by upstream 2.2.0). D36HD, D2710 and D315S also get Smart Bulb Mode where the firmware supports it.
- **"Cloud Push" diagnostic entity** per residence, showing whether the real-time push connection is up. Disabled by default; enable it when troubleshooting a site.
- **Push outages are visible in a default log:** the first failed reconnect of an outage is logged once as a warning (later retries only at debug level), and a reconnect after more than a minute logs "Leviton push reconnected after XmYYs".

### Changed
- **Only entities that control a load are enabled by default:** lights, fans, and the on/off switch of outlets and switches. A typical 27-switch home used to create ~470 entities, of which only 27 controlled a light, so control systems that import the `light` and `switch` domains (e.g. ELAN) also picked up Smart Bulb Mode, Status LED, Randomization and schedule switches. Everything else (device settings, level presets, LED options, firmware updates, diagnostics, Matter pairing codes, identify/keypad/activity buttons, scenes, schedules, keypad events) is now created disabled and can be enabled from Settings → Entities. This applies when an entity is first registered, so existing installs keep their current entities; devices added later follow the new default.

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
