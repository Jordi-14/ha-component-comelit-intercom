"""DataUpdateCoordinator for Comelit."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .comelit_client import IconaBridgeClient
from .const import CONF_HOST, CONF_TOKEN, DOMAIN, UPDATE_INTERVAL
from .control_discovery import (
    CONTROL_TYPE_ACTUATOR,
    control_identity,
    extract_controls_from_vip,
)
from .video.auth import authenticate as authenticate_video_client
from .video.client import IconaBridgeClient as VideoIconaBridgeClient
from .video.config import device_config_from_vip
from .video.rtsp_server import LocalRtspServer
from .video.video_call import VideoCallSession

_LOGGER = logging.getLogger(__name__)


class ComelitDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manage Comelit controls and the optional live video session."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.host = entry.data[CONF_HOST]
        self.token = entry.data[CONF_TOKEN]
        self.vip_config: dict[str, Any] = {}

        # The device may accept only one active ICONA client. Serialize polling,
        # relay control, video startup, and video teardown around one lock.
        self._operation_lock = asyncio.Lock()
        self._video_start_lock = asyncio.Lock()
        self._video_client: VideoIconaBridgeClient | None = None
        self._video_session: VideoCallSession | None = None
        self._rtsp_server: LocalRtspServer | None = None
        self._rtsp_url: str | None = None
        self._video_ready_event = asyncio.Event()
        self._on_stop_video: dict[Callable[[], Awaitable[None]], None] = {}
        self._on_video_state_change: dict[Callable[[], Awaitable[None]], None] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    @property
    def video_available(self) -> bool:
        """Return whether the local RTSP relay is ready."""
        return self._rtsp_server is not None and self._rtsp_url is not None

    @property
    def video_session(self) -> VideoCallSession | None:
        """Return the active video session, if any."""
        return self._video_session

    @property
    def rtsp_url(self) -> str | None:
        """Return the loopback RTSP URL exposed to Home Assistant."""
        return self._rtsp_url

    @property
    def video_ready_event(self) -> asyncio.Event:
        """Return the event set after the first video media packet arrives."""
        return self._video_ready_event

    async def async_setup_video(self) -> None:
        """Start the persistent local RTSP relay."""
        if self._rtsp_server is not None:
            return

        server = LocalRtspServer()
        try:
            self._rtsp_url = await server.start()
        except Exception:
            with contextlib.suppress(Exception):
                await server.stop()
            raise
        self._rtsp_server = server
        _LOGGER.info("Comelit local RTSP relay started at %s", self._rtsp_url)

    async def async_shutdown_video(self) -> None:
        """Stop video resources owned by the config entry."""
        await self.async_stop_video()
        server, self._rtsp_server = self._rtsp_server, None
        self._rtsp_url = None
        if server:
            with contextlib.suppress(Exception):
                await server.stop()

    def add_stop_video_callback(
        self, callback: Callable[[], Awaitable[None]]
    ) -> Callable[[], None]:
        """Register an async callback invoked before video teardown."""
        self._on_stop_video[callback] = None

        def remove() -> None:
            self._on_stop_video.pop(callback, None)

        return remove

    def add_video_state_change_callback(
        self, callback: Callable[[], Awaitable[None]]
    ) -> Callable[[], None]:
        """Register an async callback invoked when video state changes."""
        self._on_video_state_change[callback] = None

        def remove() -> None:
            self._on_video_state_change.pop(callback, None)

        return remove

    async def _notify_video_state_change(self) -> None:
        """Notify registered camera entities of a video lifecycle change."""
        for callback in list(self._on_video_state_change):
            try:
                await callback()
            except Exception:
                _LOGGER.exception("Error in Comelit video state callback")

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch controls from Comelit without interrupting active video."""
        async with self._operation_lock:
            if self._video_session is not None:
                if self.data:
                    return dict(self.data)
                return {"doors": [], "vip": self.vip_config}

            client = IconaBridgeClient(self.host)
            try:
                await client.connect()

                auth_code = await client.authenticate(self.token)
                if auth_code != 200:
                    raise ConfigEntryAuthFailed(
                        f"Authentication failed with code {auth_code}"
                    )

                config = await client.get_config("all")
                if not config or "vip" not in config:
                    raise UpdateFailed("Failed to get configuration from device")

                self.vip_config = config["vip"]
                doors = extract_controls_from_vip(self.vip_config)
                return {"doors": doors, "vip": self.vip_config}

            except ConfigEntryAuthFailed:
                raise
            except Exception as err:
                _LOGGER.error("Error communicating with Comelit device: %s", err)
                raise UpdateFailed(f"Error communicating with device: {err}") from err
            finally:
                await client.shutdown()

    async def async_open_control(self, control: dict[str, Any]) -> None:
        """Open a door or actuator, stopping video first if necessary."""
        if self._video_session is not None:
            await self.async_stop_video()

        async with self._operation_lock:
            door_client = IconaBridgeClient(self.host)
            try:
                await door_client.connect()

                auth_code = await door_client.authenticate(self.token)
                if auth_code != 200:
                    raise HomeAssistantError(
                        f"Comelit authentication failed with code {auth_code}"
                    )

                controls = (self.data or {}).get("doors", [])
                matched_control = next(
                    (
                        item
                        for item in controls
                        if control_identity(item) == control_identity(control)
                    ),
                    None,
                )
                if not matched_control:
                    raise HomeAssistantError(
                        "Control "
                        f"{control.get('control-type')} "
                        f"{control.get('apt-address')}#"
                        f"{control.get('output-index')} not found"
                    )

                if matched_control.get("control-type") == CONTROL_TYPE_ACTUATOR:
                    await door_client.open_actuator(self.vip_config, matched_control)
                else:
                    await door_client.open_door(self.vip_config, matched_control)

            except HomeAssistantError:
                raise
            except Exception as err:
                message = (
                    "Failed to open "
                    f"{control.get('control-type')} control "
                    f"{control.get('apt-address')}#"
                    f"{control.get('output-index')}: {err}"
                )
                _LOGGER.error("%s", message)
                raise HomeAssistantError(message) from err
            finally:
                await door_client.shutdown()

    async def async_start_video(self) -> VideoCallSession:
        """Negotiate an outbound video call and begin the local RTSP feed."""
        if not self.video_available:
            raise HomeAssistantError("The local Comelit RTSP relay is unavailable")

        if self._video_start_lock.locked():
            if self._video_session is not None:
                return self._video_session
            raise HomeAssistantError("A Comelit video session is already starting")

        async with self._video_start_lock:
            async with self._operation_lock:
                await self._async_stop_video_locked()

                video_config = device_config_from_vip(self.vip_config)
                if not video_config.apt_address:
                    raise HomeAssistantError(
                        "The Comelit configuration has no apartment address"
                    )

                client = VideoIconaBridgeClient(self.host)
                server = self._rtsp_server
                assert server is not None
                server.mark_not_ready()
                server.disconnect_clients()
                self._video_ready_event.clear()

                try:
                    await client.connect()
                    await authenticate_video_client(client, self.token)
                    session = VideoCallSession(
                        client,
                        video_config,
                        auto_timeout=False,
                        rtsp_server=server,
                        on_call_end=self._on_video_call_end,
                    )
                    await session.start()
                except Exception as err:
                    with contextlib.suppress(Exception):
                        await client.disconnect()
                    server.mark_not_ready()
                    raise HomeAssistantError(
                        f"Failed to start Comelit video: {err}"
                    ) from err

                self._video_client = client
                self._video_session = session
                self._video_ready_event.set()
                server.mark_ready()

            await self._notify_video_state_change()
            return session

    async def async_stop_video(self) -> None:
        """Stop an active or partially established video session."""
        async with self._video_start_lock:
            async with self._operation_lock:
                changed = await self._async_stop_video_locked()

            if changed:
                await self._notify_video_state_change()

    async def _async_stop_video_locked(self) -> bool:
        """Stop video while the caller holds the operation lock."""
        session, self._video_session = self._video_session, None
        client, self._video_client = self._video_client, None
        changed = session is not None or client is not None
        self._video_ready_event.clear()

        for callback in list(self._on_stop_video):
            try:
                await callback()
            except Exception:
                _LOGGER.exception("Error preparing Comelit camera teardown")

        try:
            if session:
                with contextlib.suppress(Exception):
                    await session.stop(reason="user request")
        finally:
            if client:
                with contextlib.suppress(Exception):
                    await client.disconnect()
            if self._rtsp_server:
                self._rtsp_server.mark_not_ready()
                self._rtsp_server.disconnect_clients()

        return changed

    def _on_video_call_end(self) -> None:
        """Schedule cleanup if the device terminates the video call."""
        self.hass.async_create_task(self.async_stop_video())
