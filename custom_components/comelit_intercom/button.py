"""Button platform for Comelit integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .control_discovery import control_identity
from .coordinator import ComelitDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit button entities."""
    coordinator: ComelitDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create button entities for each door
    entities = []
    doors = (coordinator.data or {}).get("doors", [])

    for door in doors:
        entities.append(ComelitDoorButton(coordinator, door))

    async_add_entities(entities)


class ComelitDoorButton(CoordinatorEntity[ComelitDataUpdateCoordinator], ButtonEntity):
    """Representation of a Comelit door button."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(
        self,
        coordinator: ComelitDataUpdateCoordinator,
        door: dict[str, Any],
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._door = door
        self._attr_name = door.get("name", "Unknown Door")

        # Create unique ID based on host and door details
        entry_unique_id = coordinator.entry.unique_id or coordinator.host
        control_type, apt_address, output_index, module_index = control_identity(door)
        module_suffix = f"_{module_index}" if module_index is not None else ""
        door_id = f"{control_type}_{apt_address}_{output_index}{module_suffix}"
        self._attr_unique_id = f"{entry_unique_id}_{door_id}"

        # Set device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_unique_id)},
            name=f"Comelit Intercom ({coordinator.host})",
            manufacturer="Comelit",
            model="ICONA Bridge",
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_open_control(self._door)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and any(
            control_identity(d) == control_identity(self._door)
            for d in (self.coordinator.data or {}).get("doors", [])
        )
