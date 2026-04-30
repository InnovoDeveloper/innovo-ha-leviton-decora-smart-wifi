# Changelog

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
