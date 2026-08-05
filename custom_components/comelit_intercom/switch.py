"""Call controls for the Comelit intercom."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ComelitDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the exterior-audio call switch."""
    coordinator: ComelitDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.device_config and coordinator.device_config.doors:
        async_add_entities([ComelitCallAudioSwitch(coordinator)])


class ComelitCallAudioSwitch(
    CoordinatorEntity[ComelitDataUpdateCoordinator], SwitchEntity
):
    """Enable or end the exterior audio portion of an intercom session."""

    _attr_has_entity_name = True
    _attr_name = "Exterior audio"
    _attr_icon = "mdi:phone"

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize the call audio switch."""
        super().__init__(coordinator)
        entry_unique_id = coordinator.entry.unique_id or coordinator.host
        self._attr_unique_id = f"{entry_unique_id}_call_audio"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_unique_id)},
            name=f"Comelit Intercom ({coordinator.host})",
            manufacturer="Comelit",
            model="ICONA Bridge",
        )
        self._remove_state_callback: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to call lifecycle state changes."""
        await super().async_added_to_hass()
        self._remove_state_callback = self.coordinator.add_video_state_change_callback(
            self._async_video_state_changed
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from call lifecycle state changes."""
        if self._remove_state_callback:
            self._remove_state_callback()
            self._remove_state_callback = None
        await super().async_will_remove_from_hass()

    async def _async_video_state_changed(self) -> None:
        """Publish a fresh switch state."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return whether a video session can carry call audio."""
        session = self.coordinator.video_session
        return bool(session and session.active)

    @property
    def is_on(self) -> bool:
        """Return whether exterior call audio is enabled."""
        session = self.coordinator.video_session
        return bool(session and session.audio_answered)

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable exterior and microphone audio transport."""
        await self.coordinator.async_enable_two_way_audio()

    async def async_turn_off(self, **kwargs: object) -> None:
        """End exterior audio and return to video-only viewing."""
        await self.coordinator.async_disable_two_way_audio()
