"""Constants used by the Leviton Decora Smart Wi-Fi integration."""

from enum import IntEnum, StrEnum

CONF_DEVICES: str = "devices"
CONF_RESIDENCES: str = "residences"
CONF_SAVE_RESPONSES: str = "save_responses"
CONF_SWITCHES_AS_LIGHTS: str = "switches_as_lights"
CONF_TIMEOUT: str = "timeout"

CONFIGURATION_URL: str = "https://my.leviton.com/home"

DATA_API: str = "api"
DATA_COORDINATOR: str = "coordinator"
DATA_OPTIONS_SNAPSHOT: str = "options_snapshot"
DATA_WEBSOCKET: str = "websocket"

CONF_LOGIN_RESPONSE: str = "login_response"

DOMAIN: str = "leviton_decora_smart_wifi"

EVENT_NOTIFICATION: str = f"{DOMAIN}_event"
UPDATE_NOTIFICATION: str = f"{DOMAIN}_update"

UNDO_UPDATE_LISTENER: str = "undo_update_listener"

DEFAULT_SAVE_LOCATION: str = f"/config/custom_components/{DOMAIN}/api/responses"
DEFAULT_SAVE_RESPONSES: bool = False
DEFAULT_SWITCHES_AS_LIGHTS: str = SwitchesAsLights.OFF

DEVICE_INFO_MANUFACTURER: str = "Leviton Manufacturing Co., Inc."
DEVICE_INFO_MODEL_RESIDENCE: str = "Residence"


class ScanInterval(IntEnum):
    """Scan interval."""

    DEFAULT = 10
    MAX = 60
    MIN = 1
    STEP = 1


class SwitchesAsLights(StrEnum):
    """How switch-type devices are presented.

    Home Assistant's core ``decora_wifi`` integration had only a light
    platform and modelled every device as a light, so installs migrating from
    it may have automations and third-party drivers (eLan, Control4) bound to
    ``light.*`` entity IDs even for non-dimming switches.
    """

    OFF = "off"
    """Switch-type devices get a switch entity. Upstream behaviour."""

    NAMED = "named"
    """Only switch-type devices whose name looks like lighting become lights."""

    ALL = "all"
    """Every switch-type device becomes a light."""


# Substrings that mark a switch-type device as controlling lighting, matched
# case-insensitively against the device name for SwitchesAsLights.NAMED. This
# mirrors the heuristic in rwoldberg/ldata-ha, which matches on "light" alone;
# it is necessarily leaky (a "Front Pendants" switch will not match), so
# SwitchesAsLights.ALL exists for installs that need every switch as a light.
LIGHT_NAME_HINTS: tuple[str, ...] = ("light",)


class Timeout(IntEnum):
    """Timeout."""

    DEFAULT = 30
    MAX = 60
    MIN = 10
    STEP = 5
