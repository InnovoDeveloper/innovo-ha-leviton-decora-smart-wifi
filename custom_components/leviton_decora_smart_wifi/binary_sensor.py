"""Support for Leviton Decora Smart Wi-Fi binary sensor entities."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICES,
    CONF_RESIDENCES,
    DATA_COORDINATOR,
    DATA_WEBSOCKET,
    DOMAIN,
    PUSH_STATUS_SIGNAL,
)
from .entity import LevitonEntity


@dataclass(frozen=True)
class LevitonBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Class to describe a Leviton Decora Smart Wi-Fi binary sensor entity."""

    is_supported: Callable[[Any], bool] = lambda device: device.has_motion_sensor


BINARY_SENSOR_DESCRIPTIONS: list[LevitonBinarySensorEntityDescription] = [
    LevitonBinarySensorEntityDescription(
        key="fault_detected",
        name="Fault Detected",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_supported=lambda device: device.is_gfci,
    ),
    LevitonBinarySensorEntityDescription(
        key="motion_occupied",
        name="Occupancy Detected",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a Leviton Decora Smart Wi-Fi binary sensor entity based on a config entry."""
    entry = hass.data[DOMAIN][config_entry.entry_id]
    conf_residences = entry[CONF_RESIDENCES]
    conf_devices = entry[CONF_DEVICES]
    coordinator = entry[DATA_COORDINATOR]
    websocket = entry.get(DATA_WEBSOCKET)
    entities: list[BinarySensorEntity] = []

    for residence in coordinator.data.residences:
        if residence.id in conf_residences:
            if websocket is not None:
                entities.append(
                    LevitonPushStatusEntity(
                        coordinator=coordinator,
                        residence_id=residence.id,
                        entity_description=PUSH_STATUS_DESCRIPTION,
                    )
                )
            for device in residence.devices:
                if device.id in conf_devices:
                    entities.extend(
                        LevitonBinarySensorEntity(
                            coordinator=coordinator,
                            residence_id=residence.id,
                            device_id=device.id,
                            entity_description=description,
                        )
                        for description in BINARY_SENSOR_DESCRIPTIONS
                        if all(
                            [
                                hasattr(device, description.key),
                                description.is_supported(device),
                            ]
                        )
                    )

    async_add_entities(entities)


class LevitonBinarySensorEntity(BinarySensorEntity, LevitonEntity):
    """Representation of a Leviton Decora Smart Wi-Fi binary sensor entity."""

    entity_description: LevitonBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return getattr(self.device, self.entity_description.key)


PUSH_STATUS_DESCRIPTION = LevitonBinarySensorEntityDescription(
    key="cloud_push",
    name="Cloud Push",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


class LevitonPushStatusEntity(BinarySensorEntity, LevitonEntity):
    """Whether the real-time push connection to the Leviton cloud is up.

    While it is off, paddle changes reach Home Assistant only through the
    periodic poll and keypad presses are not received at all.
    """

    entity_description: LevitonBinarySensorEntityDescription

    @property
    def available(self) -> bool:
        """Stay available when polling fails; that is when this matters most."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True while the push connection is up."""
        entry = self.hass.data.get(DOMAIN, {}).get(self.coordinator.config_entry.entry_id, {})
        websocket = entry.get(DATA_WEBSOCKET)
        return bool(websocket is not None and websocket.connected)

    async def async_added_to_hass(self) -> None:
        """Follow connect/disconnect signals from the WebSocket."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{PUSH_STATUS_SIGNAL}_{self.coordinator.config_entry.entry_id}",
                self._handle_push_status,
            )
        )

    @callback
    def _handle_push_status(self, _connected: bool) -> None:
        self.async_write_ha_state()
