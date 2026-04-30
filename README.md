[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
# Leviton Decora Smart Wi-Fi Home Assistant Integration
Custom component to allow control of [Leviton Decora Smart Wi-Fi devices](https://www.leviton.com/en/products/brands/decora-smart) in [Home Assistant](https://home-assistant.io).

> **This is an Innovo fork of the original integration by [@schmittx](https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi).** It adds real-time cloud push for physical button presses on scene controllers (DW4BC, D2SCS) via the MyLeviton websocket — the upstream "Future Plans" item from the [original README](https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi). The websocket and event-platform additions in this fork are MIT-licensed under the same terms as upstream and are intended to be contributed back via pull request. All credit for the original integration belongs to Matt Schmitt.

## What's new in this fork (v1.8.0)
- **Cloud websocket push (`iot_class: cloud_push`)** — Real-time delivery of device state changes and physical button presses on scene controllers, replacing the 120s polling delay (typical end-to-end latency: ~2 seconds).
- **`event` platform** — One `event` entity per controller button. Fires a `press` event with `trigger`, `button`, `rssi`, and `lastUpdated` attributes whenever the cloud reports a physical press. Use it as a normal HA state trigger in automations:
  ```yaml
  triggers:
    - trigger: state
      entity_id: event.<your_controller>_<button_name>_press
      not_from: [unavailable, unknown]
      not_to:   [unavailable, unknown]
  ```
- **Conservative re-auth strategy** — The websocket reuses the bearer token persisted at config-flow time and never re-logs-in on reconnect. On auth-rejected, it cools down 1 hour before retrying. This avoids triggering Leviton's "too many failed attempts" account lockout.
- **Polling-layer connection retry** — Adds a single retry on `RemoteDisconnected` so a stale keep-alive socket no longer flips every device to `unavailable` until the next poll.

## Important caveat about button events
Leviton's cloud only emits a `btnPress` notification if the pressed button has at least one action configured in the **MyLeviton mobile app**. An unbound button is silent — there is no separate raw-press channel. Bind each button you want to expose in HA to *any* placeholder action in the Leviton app (a no-op scene works fine), and the cloud will start pushing presses for it.

## Features
- Complete rewrite of the existing Home Assistant core integration with support for additional devices (from upstream).
- Additional entities to manage configuration for each device (auto shutoff, max/min dimming levels, etc.).
- Support for activities (`button`), Home/Away status (`select`), scenes (`scene`), and schedules (`switch`).
- Support for two-factor authentication.
- **Real-time button press events** via cloud websocket (this fork).

## Install
1. Ensure Home Assistant is updated to version 2026.3.0 or newer.
2. Use HACS and add this repository as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories); or download and manually move to the `custom_components` folder.
3. Once installed, follow the standard process to set up via UI and search for `Leviton Decora Smart Wi-Fi`.
4. Follow the prompts.

## Options
- Residences and devices can be updated via integration options.
- If `Advanced Mode` is enabled for the current profile, additional options are available (interval, timeout, and response logging).

## Debugging
Live debug logging without a HA restart:
```yaml
service: logger.set_level
data:
  custom_components.leviton_decora_smart_wifi: debug
```

## Supported Devices
### Controllers
- D2SCS
- DW4BC
### Fans
- D24SF
- DW4SF
### GFCI Outlets
- D2GF1
- D2GF2
### Lights
- D23LP
- D26HD
- D2ELV
- D2MSD
- DW1KD
- DW3HL
- DW6HD
- DWVAA
### Motion Sensors
- D2MSD
### Outlets
- D215P
- D215R
- DW15A
- DW15P
- DW15R
### Switches
- D215O
- D215S
- D2SCS
- DW15S

## Future Plans (upstream)
- Control of night settings start/end time
- Support for D2GF2, DN15S, DN6HD, MLWSB

## Credits
- Upstream integration: [Matt Schmitt (@schmittx)](https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi)
- Websocket protocol reverse-engineering informed by the [homebridge-myleviton](https://github.com/tbaur/homebridge-myleviton) plugin (Apache-2.0) and the [ldata-ha](https://github.com/rwoldberg/ldata-ha) integration's auth pattern.
- Websocket implementation, event platform, and connection-resilience changes in this fork: Innovo IoT.
