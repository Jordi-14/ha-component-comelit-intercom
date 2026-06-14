"""Config flow for Comelit integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .comelit_client import IconaBridgeClient
from .const import DOMAIN
from .token_extractor import extract_token

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
else:
    ConfigFlowResult = FlowResult

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_TOKEN): str,
    }
)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    _LOGGER.info("Starting validation for Comelit device at %s", data[CONF_HOST])

    # If no token provided, try to extract it automatically
    token = data.get(CONF_TOKEN)
    if not token:
        _LOGGER.info("No token provided, attempting automatic extraction")

        try:
            token = await asyncio.wait_for(extract_token(data[CONF_HOST]), timeout=30.0)
        except TimeoutError:
            _LOGGER.error("Token extraction timed out after 30 seconds")
            token = None
        except Exception as e:
            _LOGGER.error(f"Token extraction failed with error: {e}")
            token = None

        if not token:
            raise InvalidAuth(
                "Failed to extract token automatically. Please check that the device is accessible and using the default 'comelit' password, or enter your token manually."
            )

        _LOGGER.info("Successfully extracted token automatically")
        # Update data with extracted token
        data = dict(data)
        data[CONF_TOKEN] = token

    client = IconaBridgeClient(data[CONF_HOST])

    try:
        try:
            # Add timeout to prevent hanging
            _LOGGER.info(
                "Attempting to connect to Comelit device at %s", data[CONF_HOST]
            )
            await asyncio.wait_for(client.connect(), timeout=10.0)
            _LOGGER.info("Successfully connected to device")
        except TimeoutError as e:
            _LOGGER.error("Connection timeout to device at %s", data[CONF_HOST])
            raise CannotConnect("Connection timeout - device not responding") from e
        except ConnectionError as err:
            _LOGGER.error("Cannot connect to device: %s", err)
            raise CannotConnect(str(err)) from err
        except OSError as err:
            # Special handling for macOS "No route to host" error
            if err.errno == 65:  # EHOSTUNREACH on macOS
                _LOGGER.error(
                    "Cannot reach device at %s:%s - possible firewall or wrong port",
                    data[CONF_HOST],
                    64100,
                )
                raise CannotConnect(
                    "Cannot reach device - check firewall settings"
                ) from err
            _LOGGER.error("Network error connecting to device: %s", err)
            raise CannotConnect(f"Network error: {err}") from err
        except Exception as err:
            _LOGGER.error("Cannot connect to device: %s", err)
            raise CannotConnect from err

        _LOGGER.info("Authenticating with device")
        auth_code = await asyncio.wait_for(
            client.authenticate(data[CONF_TOKEN]), timeout=15.0
        )

        if auth_code != 200:
            _LOGGER.error("Authentication failed with code %s", auth_code)
            raise InvalidAuth(f"Authentication failed with code {auth_code}")

        _LOGGER.info("Authentication successful, getting configuration")

        # Get configuration to verify everything works
        config = await asyncio.wait_for(client.get_config("all"), timeout=15.0)

        if not config:
            raise CannotConnect("Failed to get configuration")

        _LOGGER.info("Configuration retrieved successfully")

        # Return info that you want to store in the config entry
        return {
            "title": f"Comelit Intercom ({data[CONF_HOST]})",
            "token": data.get(CONF_TOKEN),  # Include token in case it was extracted
        }

    except TimeoutError as err:
        _LOGGER.error("Operation timeout while communicating with device: %s", err)
        _LOGGER.error("This could be during connect, auth, or config retrieval")
        raise CannotConnect("Device communication timeout") from err
    except InvalidAuth:
        raise
    except CannotConnect:
        raise
    except Exception as err:
        _LOGGER.exception("Unexpected error during validation: %s", err)
        raise CannotConnect(f"Unexpected error: {err}") from err
    finally:
        await client.shutdown()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Comelit."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
                description_placeholders={
                    "token_help": "Leave token empty to try automatic extraction"
                },
            )

        errors = {}
        validated_data = None

        try:
            info = await validate_input(self.hass, user_input)
            # Get the potentially updated data (with extracted token)
            validated_data = user_input.copy()
            if not user_input.get(CONF_TOKEN) and info.get("token"):
                validated_data[CONF_TOKEN] = info["token"]
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth as e:
            errors["base"] = "invalid_auth"
            # If auto-extraction failed, show more helpful error
            if "extract token automatically" in str(e):
                errors["base"] = "auto_token_failed"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # Check if already configured
            await self.async_set_unique_id(validated_data[CONF_HOST])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=info["title"], data=validated_data)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "token_help": "Leave token empty to try automatic extraction"
            },
        )
