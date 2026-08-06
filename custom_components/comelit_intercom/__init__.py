"""The Comelit Intercom integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import ComelitDataUpdateCoordinator
from .video.exceptions import AuthenticationError

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.CAMERA]

OBSOLETE_ENTITY_UNIQUE_ID_SUFFIXES = (
    "video_start",
    "video_stop",
    "call_audio",
    "doorbell",
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Remove the Lovelace resource bundled by earlier intercom betas."""
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return True
    resources = (
        lovelace.resources if hasattr(lovelace, "resources") else lovelace["resources"]
    )
    await resources.async_get_info()
    if isinstance(resources, ResourceStorageCollection):
        for item in list(resources.async_items()):
            if item.get("url", "").startswith(
                "/comelit_intercom/comelit-intercom-card.js"
            ):
                await resources.async_delete_item(item["id"])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Comelit from a config entry."""
    coordinator = ComelitDataUpdateCoordinator(hass, entry)

    try:
        await coordinator.async_setup_video()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed("Authentication failed") from err
    except Exception as err:
        raise ConfigEntryNotReady("Failed to connect to Comelit device") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    _remove_obsolete_intercom_entities(hass, entry, coordinator.host)

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_shutdown_video()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    return True


def _remove_obsolete_intercom_entities(
    hass: HomeAssistant, entry: ConfigEntry, host: str
) -> None:
    """Remove retired call controls while preserving camera and door buttons."""
    registry = er.async_get(hass)
    entry_unique_id = entry.unique_id or host
    obsolete_unique_ids = {
        f"{entry_unique_id}_{suffix}" for suffix in OBSOLETE_ENTITY_UNIQUE_ID_SUFFIXES
    }
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform == DOMAIN and entity.unique_id in obsolete_unique_ids:
            registry.async_remove(entity.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: ComelitDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_shutdown_video()
        hass.data[DOMAIN].pop(entry.entry_id)

    return bool(unload_ok)
