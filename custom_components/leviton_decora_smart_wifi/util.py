"""Utilities for Leviton Decora Smart Wi-Fi integration."""

from .const import DOMAIN, LIGHT_NAME_HINTS, SwitchesAsLights


def generate_device_identifier(identifier: int | str) -> tuple[str, str]:
    """Generate device identifier."""
    return (DOMAIN, str(identifier))


def switch_presents_as_light(device, switches_as_lights: str) -> bool:
    """Return whether a switch-type device should be exposed as a light.

    Both the light and switch platforms consult this, so the two can never
    disagree and leave a device with no entity or two competing ones.
    """
    if not device.is_switch:
        return False
    if switches_as_lights == SwitchesAsLights.ALL:
        return True
    if switches_as_lights == SwitchesAsLights.NAMED:
        name = (device.name or "").lower()
        return any(hint in name for hint in LIGHT_NAME_HINTS)
    return False
