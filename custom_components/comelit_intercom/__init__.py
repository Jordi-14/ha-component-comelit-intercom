"""The Comelit Intercom integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import ComelitDataUpdateCoordinator
from .video.exceptions import AuthenticationError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.NUMBER,
    Platform.SWITCH,
]

CARD_URL = "/comelit_intercom/comelit-intercom-card.js"
CARD_PATH = Path(__file__).parent / "www" / "comelit-intercom-card.js"
SERVICE_STOP_VIDEO = "stop_video"
STOP_VIDEO_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})

OBSOLETE_ENTITY_UNIQUE_ID_SUFFIXES = (
    "video_start",
    "video_stop",
    "call_audio",
    "doorbell",
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register the privacy-aware intercom camera card."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={INTEGRATION_VERSION}")
    if not hass.services.has_service(DOMAIN, SERVICE_STOP_VIDEO):

        async def _handle_stop_video(call: ServiceCall) -> None:
            await _async_stop_dashboard_video(hass, call.data[ATTR_ENTITY_ID])

        hass.services.async_register(
            DOMAIN,
            SERVICE_STOP_VIDEO,
            _handle_stop_video,
            schema=STOP_VIDEO_SCHEMA,
        )

    # Earlier betas stored this resource in Lovelace. The integration now
    # registers it with the frontend directly, so remove stale stored copies.
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
            if item.get("url", "").startswith(CARD_URL):
                await resources.async_delete_item(item["id"])
                _LOGGER.debug("Removed stale stored Comelit card resource")
    return True


async def _async_stop_dashboard_video(hass: HomeAssistant, entity_id: str) -> None:
    """Stop a card-owned session, including one still negotiating."""
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None or entity.config_entry_id is None:
        return
    coordinator = hass.data.get(DOMAIN, {}).get(entity.config_entry_id)
    if coordinator is None:
        return
    coordinator.request_video_stop()
    await coordinator.async_stop_video(reason="dashboard card hidden")


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
