"""Tests for the split video and exterior-audio lifecycle."""

from __future__ import annotations

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
