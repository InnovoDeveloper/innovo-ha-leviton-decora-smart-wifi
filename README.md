[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
# Leviton Decora Smart Wi-Fi Home Assistant Integration
Custom component to allow control of [Leviton Decora Smart Wi-Fi devices](https://www.leviton.com/en/products/brands/decora-smart) in [Home Assistant](https://home-assistant.io).

> **This is an Innovo fork of the integration by [@schmittx](https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi), tracking upstream `2.1.3`.** All credit for the integration itself belongs to Matt Schmitt. This fork is MIT-licensed under the same terms as upstream, and its changes are intended to be contributed back via pull request.
>
> The real-time cloud push (websocket) work that originated in this fork has since been **merged upstream** and now ships in schmittx `2.1.x` — it is no longer a difference between the two. What this fork currently adds on top of upstream is described below.

## What this fork adds on top of upstream 2.1.3
- **Automatic access-token renewal.** Upstream only re-authenticates when the API returns the exact string `"Invalid Access Token"`. Leviton answers an expired bearer with `"Authorization Required"`, so upstream never re-logs-in and the integration stays dead once its token expires. This fork keys recovery off the 401 status itself.
- **Rate-limited logins (`api/throttle.py`).** Every automatic re-login — REST and websocket alike — goes through a shared throttle: 60s minimum spacing, exponential failure backoff (60s → 1h), a 1h cooldown on Leviton's `403 Too many failed attempts`, and a hard ceiling of 5 logins per rolling hour. This is what makes automatic renewal safe to run unattended, without risking an account lockout.
- **Refreshed tokens are persisted** back to the config entry, and the options-update listener compares against a snapshot so a token write no longer triggers an entry reload.
- **Setup failures are retryable.** Setup raises `ConfigEntryNotReady` rather than dereferencing coordinator data that a failed first fetch never populated. A transient network problem at startup — a DNS blip while the network is still coming up at boot is the common one — now enters Home Assistant's automatic backoff retry instead of leaving the entry in `SETUP_ERROR`, a state Home Assistant never retries.

## Features
- This is an complete rewrite of the existing Home Assistant core integration with support for additional devices.
- Additional entities have been added to manage configuration for each device as well (ex. auto shutoff, max/min dimming levels, etc.).
- Support for activities (`button`), Home/Away status (`select`), scenes (`scene`), and schedules (`switch`) is also included.
- Support for two-factor authentication.
- **Real-time cloud push via the MyLeviton websocket**
    - State changes on all devices in general are reflected instantly
    - Physical button presses on scene controllers (DW4BC, D2SCS) are reflected in a few seconds (due to limitations from Leviton's API).
    - Changes for residence, schedules, or activities still rely on polling

## Button presses
Each controller button is exposed as an `event` entity (e.g. `event.<controller>_<button_name>_press`). Use it as a state trigger in automations:

```yaml
triggers:
  - trigger: state
    entity_id: event.your_controller_button_1_press
    not_from: [unavailable, unknown]
    not_to:   [unavailable, unknown]
```

*Note: Leviton's API only emits `btnPress` notifications for buttons that have at least one action configured in the MyLeviton mobile app. Bind each button you want to expose in Home Assistant to any placeholder action in the MyLeviton app, the button itself doesn't need to do anything meaningful for Home Assistant to receive the press.*

## Install
1. Ensure Home Assistant is updated to version 2026.6.0 or newer.
2. In HACS, add this repository as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories) with category `Integration`:
   ```
   https://github.com/InnovoDeveloper/innovo-ha-leviton-decora-smart-wifi
   ```
   Or download it and move `custom_components/leviton_decora_smart_wifi` into your `custom_components` folder manually.

   If you already have the upstream schmittx integration installed through HACS, remove it first — both use the same `leviton_decora_smart_wifi` domain and would otherwise overwrite each other. Your existing config entry, entity IDs and history are preserved across the switch.
3. Once the integration is installed follow the standard process to setup via UI and search for `Leviton Decora Smart Wi-Fi`.
4. Follow the prompts.

## Options
- Residences, devices, polling interval, polling timeout, and response logging can be configured via integration options.

## Debugging
Raise the log level without restarting Home Assistant:
```yaml
action: logger.set_level
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
- DN6HD
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
- DN15S
- DW15S

## Future Plans
- Control of night settings start/end time

## Notes
- `DN15S` and `DN6HD` devices may report bridge linkage through diagnostic data such as `Bridge Serial`.
- The required `MLWSB` bridge is not currently exposed by the My Leviton cloud device list as a standalone selectable device, so it is not added as its own Home Assistant device by this integration.

## Credits
- Original integration and all ongoing upstream work: [Matt Schmitt (@schmittx)](https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi).
- Websocket protocol reverse-engineering was informed by the [homebridge-myleviton](https://github.com/tbaur/homebridge-myleviton) plugin (Apache-2.0) and the auth pattern in the [ldata-ha](https://github.com/rwoldberg/ldata-ha) integration.
- Token-renewal hardening and login rate limiting in this fork: Innovo IoT.
