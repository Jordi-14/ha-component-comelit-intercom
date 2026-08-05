"""Tests for the split video and exterior-audio lifecycle."""

from __future__ import annotations

import asyncio
import struct
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "comelit_intercom"
)


def _package(name: str, path: Path) -> None:
    """Load a package namespace without executing the HA integration setup."""
    if name in sys.modules:
        return
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package


try:
    from homeassistant.exceptions import HomeAssistantError as _HomeAssistantError
except ImportError:
    homeassistant = types.ModuleType("homeassistant")
    exceptions = types.ModuleType("homeassistant.exceptions")

    class _HomeAssistantError(Exception):
        """Minimal Home Assistant exception used by protocol tests."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args)

    exceptions.HomeAssistantError = _HomeAssistantError
    homeassistant.exceptions = exceptions
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.exceptions"] = exceptions


_package("custom_components", COMPONENT_DIR.parent)
_package("custom_components.comelit_intercom", COMPONENT_DIR)
_package("custom_components.comelit_intercom.video", COMPONENT_DIR / "video")

from custom_components.comelit_intercom.video.exceptions import (  # noqa: E402
    VideoCallError,
)
from custom_components.comelit_intercom.video.video_call import (  # noqa: E402
    VideoCallSession,
)


@pytest.mark.asyncio
async def test_outbound_audio_runs_answer_sequence_before_sender() -> None:
    """An outbound view becomes a call only after audio is explicitly enabled."""
    session = VideoCallSession.__new__(VideoCallSession)
    session._audio_answered = False
    session._inbound = False
    session._device_rtpc_req_id = 123
    session._answer_context = (
        MagicMock(),
        MagicMock(),
        "SB0000061",
        "SB100001",
        "SB000006",
        1,
        2,
    )
    session._run_answer_sequence = AsyncMock()
    session._rtp_receiver = MagicMock()

    await session.enable_two_way_audio()

    session._run_answer_sequence.assert_awaited_once_with(*session._answer_context)
    session._rtp_receiver.start_audio_sender.assert_called_once_with(123)
    assert session.audio_answered is True


@pytest.mark.asyncio
async def test_inbound_audio_does_not_repeat_outbound_answer_sequence() -> None:
    """Inbound signaling is already answered before its audio path is enabled."""
    session = VideoCallSession.__new__(VideoCallSession)
    session._audio_answered = False
    session._inbound = True
    session._device_rtpc_req_id = 456
    session._answer_context = None
    session._run_answer_sequence = AsyncMock()
    session._rtp_receiver = MagicMock()

    await session.enable_two_way_audio()

    session._run_answer_sequence.assert_not_awaited()
    session._rtp_receiver.start_audio_sender.assert_called_once_with(456)
    assert session.audio_answered is True


@pytest.mark.asyncio
async def test_enabling_audio_is_idempotent() -> None:
    """Repeated UI state updates must not renegotiate the device call."""
    session = VideoCallSession.__new__(VideoCallSession)
    session._audio_answered = True
    session._inbound = False
    session._answer_context = None
    session._run_answer_sequence = AsyncMock()
    session._rtp_receiver = MagicMock()
    session._device_rtpc_req_id = 789

    await session.enable_two_way_audio()

    session._run_answer_sequence.assert_not_awaited()
    session._rtp_receiver.start_audio_sender.assert_not_called()


@pytest.mark.asyncio
async def test_periodic_config_ack_does_not_restart_session() -> None:
    """A recurring 0x0003/0x000E message is ACKed without resetting media."""
    session = VideoCallSession.__new__(VideoCallSession)
    session._active = True
    session._ctpp_lock = asyncio.Lock()
    session._call_counter = 0
    session._inline_reestablish = AsyncMock()
    response = struct.pack("<HI", 0x1840, 1) + struct.pack(">HH", 0x0003, 0x000E)
    client = MagicMock()
    client.read_response = AsyncMock(return_value=response)

    async def stop_after_ack(*_args: object) -> None:
        session._active = False

    client.send_binary = AsyncMock(side_effect=stop_after_ack)

    await session._ctpp_monitor_loop(client, MagicMock(), "A1", "B1", 1, 2, 3)

    client.send_binary.assert_awaited_once()
    session._inline_reestablish.assert_not_awaited()


@pytest.mark.asyncio
async def test_zero_sub_status_renews_expired_session() -> None:
    """A true 0x0003/0x0000 lease expiry still renews the call."""
    session = VideoCallSession.__new__(VideoCallSession)
    session._active = True
    session._ctpp_lock = asyncio.Lock()
    session._call_counter = 0
    response = struct.pack("<HI", 0x1840, 1) + struct.pack(">HH", 0x0003, 0x0000)
    client = MagicMock()
    client.read_response = AsyncMock(return_value=response)

    async def renew(*_args: object) -> int:
        session._active = False
        return 42

    session._inline_reestablish = AsyncMock(side_effect=renew)

    await session._ctpp_monitor_loop(client, MagicMock(), "A1", "B1", 1, 2, 3)

    session._inline_reestablish.assert_awaited_once()
    assert session._call_counter == 42


@pytest.mark.asyncio
async def test_missing_media_is_a_start_failure() -> None:
    """A signaled call with no RTP is not exposed as a ready black stream."""
    receiver = MagicMock()
    receiver.wait_for_first_video = AsyncMock(side_effect=TimeoutError)
    receiver.udp_media_packet_count = 0
    receiver.tcp_media_packet_count = 0

    with pytest.raises(VideoCallError) as error:
        await VideoCallSession._require_first_video(receiver)

    assert error.value.translation_key == "video_media_not_received"
