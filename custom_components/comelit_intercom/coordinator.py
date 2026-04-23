"""DataUpdateCoordinator for Comelit."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .comelit_client import IconaBridgeClient
from .const import CONF_HOST, CONF_TOKEN, DOMAIN, UPDATE_INTERVAL
from .control_discovery import (
    CONTROL_TYPE_ACTUATOR,
    control_identity,
    extract_controls_from_vip,
)

_LOGGER = logging.getLogger(__name__)


class ComelitDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Comelit data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.host = entry.data[CONF_HOST]
        self.token = entry.data[CONF_TOKEN]
        self.client = IconaBridgeClient(self.host)
        self.vip_config: dict[str, Any] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Comelit."""
        try:
            await self.client.connect()

            # Authenticate
            auth_code = await self.client.authenticate(self.token)
            if auth_code != 200:
                raise ConfigEntryAuthFailed(
                    f"Authentication failed with code {auth_code}"
                )

            # Get configuration
            config = await self.client.get_config("all")
            if not config or "vip" not in config:
                raise UpdateFailed("Failed to get configuration from device")

            self.vip_config = config["vip"]
            doors = extract_controls_from_vip(self.vip_config)

            return {"doors": doors, "vip": self.vip_config}

        except ConfigEntryAuthFailed:
            # Re-raise auth errors
            raise
        except Exception as err:
            _LOGGER.error("Error communicating with Comelit device: %s", err)
            raise UpdateFailed(f"Error communicating with device: {err}") from err
        finally:
            # Always close the connection after update
            await self.client.shutdown()

    async def async_open_control(self, control: dict[str, Any]) -> None:
        """Open a specific door or actuator control."""
        # Create a separate client instance for door operations
        # to avoid interfering with the coordinator's update cycle
        door_client = IconaBridgeClient(self.host)
        try:
            await door_client.connect()

            # Authenticate
            auth_code = await door_client.authenticate(self.token)
            if auth_code != 200:
                raise Exception(f"Authentication failed with code {auth_code}")

            # Find the latest copy of the control from the coordinator data
            controls = self.data.get("doors", [])
            matched_control = next(
                (item for item in controls if control_identity(item) == control_identity(control)),
                None,
            )
            if not matched_control:
                raise Exception(
                    "Control "
                    f"{control.get('control-type')} "
                    f"{control.get('apt-address')}#{control.get('output-index')} not found"
                )

            if matched_control.get("control-type") == CONTROL_TYPE_ACTUATOR:
                await door_client.open_actuator(self.vip_config, matched_control)
            else:
                await door_client.open_door(self.vip_config, matched_control)

        except Exception as err:
            _LOGGER.error(
                "Error opening %s control %s#%s: %s",
                control.get("control-type"),
                control.get("apt-address"),
                control.get("output-index"),
                err,
            )
            raise
        finally:
            # Always clean up the door client connection
            await door_client.shutdown()
