"""Doorbell and call lifecycle events for Comelit intercoms."""

from __future__ import annotations

from homeassistant.components.event import (
    DoorbellEventType,
    EventDeviceClass,
    EventEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ComelitDataUpdateCoordinator
from .video.models import PushEvent

EVENT_TYPES = [
    DoorbellEventType.RING,
    "missed_call",
    "door_opened",
    "call_ended",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Comelit doorbell event entity."""
    coordinator: ComelitDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ComelitDoorbellEvent(coordinator)])


class ComelitDoorbellEvent(EventEntity):
    """Report momentary doorbell and call lifecycle events."""

    _attr_has_entity_name = True
    _attr_name = "Doorbell"
    _attr_event_types = EVENT_TYPES
    _attr_device_class = EventDeviceClass.DOORBELL

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize the event entity."""
        self.coordinator = coordinator
        entry_unique_id = coordinator.entry.unique_id or coordinator.host
        self._attr_unique_id = f"{entry_unique_id}_doorbell"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_unique_id)},
            name=f"Comelit Intercom ({coordinator.host})",
            manufacturer="Comelit",
            model="ICONA Bridge",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to protocol events."""
        self.async_on_remove(self.coordinator.add_push_callback(self._on_push))

    @callback
    def _on_push(self, event: PushEvent) -> None:
        """Publish a supported event to Home Assistant."""
        if event.event_type not in EVENT_TYPES:
            return
        data: dict[str, object] = {"apt_address": event.apt_address}
        if event.raw:
            data.update(event.raw)
        self._trigger_event(event.event_type, data)
        self.async_write_ha_state()
