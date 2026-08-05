"""The Comelit Intercom integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import ComelitDataUpdateCoordinator
from .video.exceptions import AuthenticationError

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.EVENT,
    Platform.SWITCH,
]
CARD_URL = "/comelit_intercom/comelit-intercom-card.js"
CARD_PATH = str(Path(__file__).parent / "www" / "comelit-intercom-card.js")
CARD_VERSION = "1.2.0b4"


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register the bundled Lovelace intercom card."""
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, CARD_PATH, cache_headers=True)]
    )
    url = f"{CARD_URL}?v={CARD_VERSION}"
    lovelace = hass.data["lovelace"]
    resources = (
        lovelace.resources if hasattr(lovelace, "resources") else lovelace["resources"]
    )
    await resources.async_get_info()
    for item in resources.async_items():
        if not item.get("url", "").startswith(CARD_URL):
            continue
        if item["url"] == url:
            return True
        if isinstance(resources, ResourceStorageCollection):
            await resources.async_update_item(
                item["id"], {"res_type": "module", "url": url}
            )
        else:
            item["url"] = url
        return True
    if isinstance(resources, ResourceStorageCollection):
        await resources.async_create_item({"res_type": "module", "url": url})
    else:
        add_extra_js_url(hass, url)
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

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_shutdown_video()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: ComelitDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_shutdown_video()
        hass.data[DOMAIN].pop(entry.entry_id)

    return bool(unload_ok)
