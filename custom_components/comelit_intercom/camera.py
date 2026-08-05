"""Camera platform for the Comelit intercom live video feed."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    CameraWebRTCProvider,
)
from homeassistant.components.camera.webrtc import (
    DATA_WEBRTC_PROVIDERS,
    WebRTCError,
    WebRTCSendMessage,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ComelitDataUpdateCoordinator
from .placeholder import PLACEHOLDER_JPEG

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the intercom camera entity."""
    coordinator: ComelitDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.device_config and coordinator.device_config.doors:
        async_add_entities([ComelitIntercomCamera(coordinator)])


class ComelitIntercomCamera(Camera):
    """Live camera stream initiated through the ICONA Bridge protocol."""

    _attr_has_entity_name = True
    _attr_name = "Live feed"
    _attr_icon = "mdi:doorbell-video"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator: ComelitDataUpdateCoordinator) -> None:
        """Initialize the camera."""
        super().__init__()
        self._coordinator = coordinator
        entry_unique_id = coordinator.entry.unique_id or coordinator.host
        self._attr_unique_id = f"{entry_unique_id}_intercom_camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_unique_id)},
            name=f"Comelit Intercom ({coordinator.host})",
            manufacturer="Comelit",
            model="ICONA Bridge",
        )
        self._remove_stop_callback: Callable[[], None] | None = None
        self._remove_state_callback: Callable[[], None] | None = None
        self._webrtc_sessions: dict[str, CameraWebRTCProvider] = {}

    @property
    def available(self) -> bool:
        """Return whether the local RTSP relay initialized successfully."""
        return self._coordinator.video_available

    @property
    def is_streaming(self) -> bool:
        """Return whether an intercom video call is active."""
        session = self._coordinator.video_session
        return session is not None and session.active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose call direction and the reason an unexpected call ended."""
        session = self._coordinator.video_session
        return {
            "call_direction": (
                ("inbound" if session and session.is_inbound else "outbound")
                if session
                else None
            ),
            "two_way_audio": bool(session and session.audio_answered),
            "last_end_reason": self._coordinator.last_video_end_reason,
            "last_end_at": self._coordinator.last_video_end_at,
        }

    async def stream_source(self) -> str | None:
        """Return the local RTSP URL once video media is ready."""
        if self.is_streaming:
            return f"{self._coordinator.rtsp_url}#backchannel=1"
        try:
            await asyncio.wait_for(
                self._coordinator.video_ready_event.wait(), timeout=8.0
            )
        except TimeoutError:
            return None
        return f"{self._coordinator.rtsp_url}#backchannel=1"

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return the latest decoded JPEG frame or an idle placeholder."""
        session = self._coordinator.video_session
        if not session or not session.active or not session.rtp_receiver:
            return PLACEHOLDER_JPEG
        try:
            async with asyncio.timeout(2.0):
                return await session.rtp_receiver.get_jpeg_frame()
        except TimeoutError:
            return session.rtp_receiver.latest_frame

    async def async_handle_async_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
    ) -> None:
        """Forward a WebRTC offer to go2rtc's two-way-audio stream."""
        if not self.is_streaming:
            try:
                await self._coordinator.async_start_video(by_user=True)
            except Exception as err:
                send_message(WebRTCError(code="video_start_failed", message=str(err)))
                return

        source = await self.stream_source()
        for provider in self.hass.data.get(DATA_WEBRTC_PROVIDERS, set()):
            if source and provider.async_is_supported(source):
                self._webrtc_sessions[session_id] = provider
                await provider.async_handle_async_webrtc_offer(
                    self, offer_sdp, session_id, send_message
                )
                return
        send_message(
            WebRTCError(
                code="webrtc_provider_unavailable",
                message="Home Assistant's go2rtc WebRTC provider is unavailable",
            )
        )

    async def async_on_webrtc_candidate(self, session_id: str, candidate: Any) -> None:
        """Forward a trickled ICE candidate to Home Assistant's provider."""
        if provider := self._webrtc_sessions.get(session_id):
            await provider.async_on_webrtc_candidate(session_id, candidate)

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Close the delegated WebRTC session."""
        if provider := self._webrtc_sessions.pop(session_id, None):
            provider.async_close_session(session_id)

    async def async_added_to_hass(self) -> None:
        """Register callbacks for video lifecycle changes."""
        await super().async_added_to_hass()
        self._remove_stop_callback = self._coordinator.add_stop_video_callback(
            self._async_stop_ha_stream
        )
        self._remove_state_callback = self._coordinator.add_video_state_change_callback(
            self._async_video_state_changed
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when the entity is removed."""
        if self._remove_stop_callback:
            self._remove_stop_callback()
            self._remove_stop_callback = None
        if self._remove_state_callback:
            self._remove_state_callback()
            self._remove_state_callback = None
        await super().async_will_remove_from_hass()

    async def _async_video_state_changed(self) -> None:
        """Refresh HA's stream provider and camera state."""
        refresh_providers = getattr(self, "async_refresh_providers", None)
        if refresh_providers is not None:
            await refresh_providers()
        self.async_write_ha_state()

    async def _async_stop_ha_stream(self) -> None:
        """Stop HA's cached stream before the RTSP socket is disconnected."""
        stream: Any = getattr(self, "stream", None)
        if stream is None:
            return
        self.stream = None
        try:
            await stream.stop()
        except Exception:
            _LOGGER.debug(
                "Error stopping the Home Assistant camera stream", exc_info=True
            )
