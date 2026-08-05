"""Button platform for Comelit integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .control_discovery import CONTROL_TYPE_ACTUATOR, control_identity
from .coordinator import ComelitDataUpdateCoordinator
from .video.models import Door

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Comelit button entities."""
    coordinator: ComelitDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create button entities for each door
    entities: list[ButtonEntity] = []
    doors = coordinator.device_config.doors if coordinator.device_config else []

    for door in doors:
        entities.append(ComelitDoorButton(coordinator, door))

    if doors:
        entities.extend(
            [
                ComelitStartVideoButton(coordinator),
                ComelitStopVideoButton(coordinator),
            ]
        )

    async_add_entities(entities)


class ComelitDoorButton(CoordinatorEntity[ComelitDataUpdateCoordinator], ButtonEntity):
    """Representation of a Comelit door button."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(
        self,
        coordinator: ComelitDataUpdateCoordinator,
        door: Door,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._door = door
        self._attr_name = door.name

        # Create unique ID based on host and door details
        entry_unique_id = coordinator.entry.unique_id or coordinator.host
        control_type, apt_address, output_index, module_index = control_identity(
            _door_control(door)
        )
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
        await self.coordinator.async_open_door(self._door)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and any(
            control_identity(_door_control(d))
            == control_identity(_door_control(self._door))
            for d in (
                self.coordinator.device_config.doors
                if self.coordinator.device_config
                else []
            )
        )


def _door_control(door: Door) -> dict[str, object]:
    """Convert a door model to the stable legacy identity fields."""
    return {
        "control-type": CONTROL_TYPE_ACTUATOR if door.is_actuator else "door",
        "apt-address": door.apt_address,
        "output-index": door.output_index,
        "module-index": door.module_index,
    }


class _ComelitVideoButton(
    CoordinatorEntity[ComelitDataUpdateCoordinator], ButtonEntity
):
    """Base class for diagnostic video controls."""

    _attr_has_entity_name = True
    _attr_entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        entry_unique_id = coordinator.entry.unique_id or coordinator.host
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_unique_id)},
            name=f"Comelit Intercom ({coordinator.host})",
            manufacturer="Comelit",
            model="ICONA Bridge",
        )

    @property
    def available(self) -> bool:
        """Return whether the video relay initialized successfully."""
        return bool(self.coordinator.video_available)


class ComelitStartVideoButton(_ComelitVideoButton):
    """Button that starts the intercom camera stream."""

    _attr_name = "Start video feed"
    _attr_icon = "mdi:video"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        entry_unique_id = coordinator.entry.unique_id or coordinator.host
        self._attr_unique_id = f"{entry_unique_id}_video_start"

    async def async_press(self) -> None:
        """Start the live video feed."""
        await self.coordinator.async_start_video(by_user=True)


class ComelitStopVideoButton(_ComelitVideoButton):
    """Button that stops the intercom camera stream."""

    _attr_name = "Stop video feed"
    _attr_icon = "mdi:video-off"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        entry_unique_id = coordinator.entry.unique_id or coordinator.host
        self._attr_unique_id = f"{entry_unique_id}_video_stop"

    async def async_press(self) -> None:
        """Stop the live video feed."""
        self.coordinator.request_video_stop()
        await self.coordinator.async_stop_video()
