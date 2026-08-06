"""Tests for the split video and exterior-audio lifecycle."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import logging
import struct
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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

from custom_components.comelit_intercom import coordinator as coordinator_module
from custom_components.comelit_intercom.video.channels import (  # noqa: E402
    Channel,
    ChannelType,
)
from custom_components.comelit_intercom.video.client import (  # noqa: E402
    IconaBridgeClient,
)
from custom_components.comelit_intercom.video.exceptions import (  # noqa: E402
    VideoCallError,
)
from custom_components.comelit_intercom.video.models import (  # noqa: E402
    DeviceConfig,
    Door,
)
from custom_components.comelit_intercom.video.rtp_receiver import (  # noqa: E402
    RtpReceiver,
)
from custom_components.comelit_intercom.video.rtsp_server import (  # noqa: E402
    LocalRtspServer,
    _TcpClient,
)
from custom_components.comelit_intercom.video.video_call import (  # noqa: E402
    VideoCallSession,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("is_actuator", [False, True])
async def test_door_buttons_use_proven_dedicated_legacy_sequence(
    is_actuator: bool,
) -> None:
    """Video state must not replace the door sequence that works on the device."""
    coordinator = coordinator_module.ComelitDataUpdateCoordinator.__new__(
        coordinator_module.ComelitDataUpdateCoordinator
    )
    coordinator.host = "192.0.2.1"
    coordinator.port = 64100
    coordinator.token = "token"
    coordinator._config = DeviceConfig(
        raw={"vip": {"apt-address": "SB000001", "apt-subaddress": 1}}
    )
    coordinator._on_push_event = MagicMock()
    door = Door(
        id=1,
        index=1,
        name="Gate" if is_actuator else "Entrance",
        apt_address="SBIO0255" if is_actuator else "SB100001",
        output_index=1,
        is_actuator=is_actuator,
    )
    client = MagicMock()
    client.connect = AsyncMock()
    client.authenticate = AsyncMock(return_value=200)
    client.open_door = AsyncMock()
    client.open_actuator = AsyncMock()
    client.shutdown = AsyncMock()

    with patch.object(coordinator_module, "LegacyDoorClient", return_value=client):
        await coordinator.async_open_door(door)

    client.connect.assert_awaited_once()
    client.authenticate.assert_awaited_once_with("token")
    if is_actuator:
        client.open_actuator.assert_awaited_once()
        client.open_door.assert_not_awaited()
    else:
        client.open_door.assert_awaited_once()
        client.open_actuator.assert_not_awaited()
    client.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_close_waits_for_device_release() -> None:
    """A video channel is not reusable until the panel completes its END flow."""
    client = IconaBridgeClient("192.0.2.1")
    writer = MagicMock()
    writer.drain = AsyncMock()
    client._writer = writer
    channel = Channel(
        name="RTPC2",
        channel_type=ChannelType.UAUT,
        request_id=123,
        server_channel_id=0x2103,
        sequence=3,
        is_open=True,
    )
    client._channels[channel.name] = channel

    close_task = asyncio.create_task(client.close_channel(channel.name))
    await asyncio.sleep(0)

    assert close_task.done() is False
    close_packet = writer.write.call_args_list[0].args[0]
    assert close_packet[4:6] == struct.pack("<H", channel.server_channel_id)
    assert close_packet[8:12] == struct.pack("<HH", 0x01EF, 3)

    device_end = struct.pack("<HHIH", 0x01EF, 3, 2, channel.server_channel_id)
    client._dispatch(0, device_end)

    assert await close_task is True
    assert channel.name not in client._channels
    close_ack = writer.write.call_args_list[1].args[0]
    assert close_ack[8:18] == struct.pack(
        "<HHIH", 0x01EF, 4, 4, channel.server_channel_id
    )


@pytest.mark.asyncio
async def test_video_cleanup_closes_remote_media_channels() -> None:
    """Cleanup sends ENDs and requests a reset when one is not acknowledged."""
    session = VideoCallSession.__new__(VideoCallSession)
    session._active = True
    session._timeout_task = None
    session._tcp_task = None
    session._ctpp_task = None
    session._rtp_receiver = None
    session._rtsp_server = None
    session._external_rtsp = True
    session._owns_ctpp = False
    session._cleanup_requires_reconnect = False
    client = MagicMock()
    client.close_channel = AsyncMock(side_effect=lambda name: name != "RTPC2")
    session._client = client

    await session._cleanup()

    closed_names = {call.args[0] for call in client.close_channel.await_args_list}
    assert closed_names == {
        "UDPM",
        "RTPC",
        "RTPC2",
        "RTPC_DEVICE",
        "RTPC_DEVICE_REEST",
    }
    assert session.cleanup_requires_reconnect is True


@pytest.mark.asyncio
async def test_video_client_redacts_authentication_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Debug logging must not expose the credential used by authentication."""
    client = IconaBridgeClient("192.0.2.1")
    writer = MagicMock()
    writer.drain = AsyncMock()
    client._writer = writer
    channel = Channel(
        name="UAUT",
        channel_type=ChannelType.UAUT,
        request_id=123,
        server_channel_id=0x2104,
        is_open=True,
    )
    client._channels[channel.name] = channel
    token = "secret-token-that-must-not-be-logged"

    with caplog.at_level(logging.DEBUG):
        response_task = asyncio.create_task(
            client.send_json(
                channel,
                {
                    "message": "access",
                    "user-token": token,
                    "message-type": "request",
                },
            )
        )
        await asyncio.sleep(0)
        client._dispatch(channel.server_channel_id, b'{"response-code":200}')
        await response_task

    assert token not in caplog.text
    assert "<redacted>" in caplog.text
    assert b"<redacted>" not in writer.write.call_args.args[0]


def test_card_uses_separate_autoplay_safe_media_elements() -> None:
    """An incoming audio track must not block muted video autoplay."""
    card = (COMPONENT_DIR / "www" / "comelit-intercom-card.js").read_text(
        encoding="utf-8"
    )

    assert '<video id="call-video" autoplay playsinline muted hidden>' in card
    assert "<audio autoplay playsinline muted>" in card
    assert 'event.track.kind === "video" ? video : audio' in card
    assert "video.play().catch" in card


def test_card_uses_low_latency_video_with_hls_fallback() -> None:
    """Normal video uses the proven signaling path with an HLS fallback."""
    card = (COMPONENT_DIR / "www" / "comelit-intercom-card.js").read_text(
        encoding="utf-8"
    )

    assert 'customElements.whenDefined("ha-hls-player")' in card
    assert 'document.createElement("ha-hls-player")' in card
    assert "stream.allowExoPlayer = true" in card
    assert "this._mountHlsStream" in card
    assert "await this._connect(false)" in card
    assert "callMode ? 12000 : 8000" in card
    assert "window.loadCardHelpers" in card
    assert 'type: "camera/webrtc/get_client_config"' in card
    assert "new RTCPeerConnection(clientConfig.configuration)" in card
    assert "event.candidate.toJSON()" in card
    assert 'sdpMid: "0"' in card
    assert "Two-way audio needs a direct WebRTC route" in card


def test_card_allows_receive_only_call_on_insecure_local_app_url() -> None:
    """A local HTTP app URL must disable only its microphone, not call mode."""
    card = (COMPONENT_DIR / "www" / "comelit-intercom-card.js").read_text(
        encoding="utf-8"
    )

    assert "window.isSecureContext" not in card
    assert "await this._setCall(true)" in card
    assert 'this._pc.addTransceiver("audio", { direction: "recvonly" })' in card
    assert 'mic.textContent = this._mic ? "MIC ON" : "MIC UNAVAILABLE"' in card
    assert "this._micEnabled = true" in card


def test_card_cache_version_matches_integration_version() -> None:
    """Every beta must force HA to load the matching bundled card asset."""
    manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text(encoding="utf-8"))
    init_source = (COMPONENT_DIR / "__init__.py").read_text(encoding="utf-8")

    assert f'CARD_VERSION = "{manifest["version"]}"' in init_source


def test_rtsp_is_video_only_until_two_way_audio_is_enabled() -> None:
    """Normal viewing must retain the first beta's proven video-only SDP."""
    server = LocalRtspServer()

    assert "m=video" in server._build_sdp()
    assert "m=audio" not in server._build_sdp()

    server.set_audio_enabled(True)

    assert server._build_sdp().count("m=audio") == 2


@pytest.mark.asyncio
async def test_rtsp_play_waits_for_real_video() -> None:
    """An idle relay must not create a successfully negotiated black producer."""
    server = LocalRtspServer()
    server._running = True
    reader = asyncio.StreamReader()
    reader.feed_data(b"PLAY rtsp://127.0.0.1/intercom RTSP/1.0\r\nCSeq: 4\r\n\r\n")
    writer = MagicMock()
    writer.get_extra_info.side_effect = lambda name: (
        ("127.0.0.1", 12345) if name == "peername" else None
    )
    writer.drain = AsyncMock()

    play_task = asyncio.create_task(server._handle_client(reader, writer))
    await asyncio.sleep(0)

    writer.write.assert_not_called()

    server.mark_ready()
    reader.feed_eof()
    await asyncio.wait_for(play_task, timeout=1)

    assert b"RTSP/1.0 200 OK" in writer.write.call_args_list[0].args[0]


@pytest.mark.asyncio
async def test_rtsp_parser_preserves_pipelined_requests() -> None:
    """A PLAY received in the same TCP read as SETUP must not be discarded."""
    server = LocalRtspServer()
    reader = asyncio.StreamReader()
    reader.feed_data(
        b"SETUP rtsp://127.0.0.1/intercom/video RTSP/1.0\r\nCSeq: 1\r\n\r\n"
        b"PLAY rtsp://127.0.0.1/intercom RTSP/1.0\r\nCSeq: 2\r\n\r\n"
    )
    buffer = bytearray()

    first = await server._read_rtsp_request(reader, buffer)
    second = await server._read_rtsp_request(reader, buffer)

    assert first is not None and first[0] == "SETUP"
    assert second is not None and second[0] == "PLAY"
    assert second[3] == "2"
    assert buffer == bytearray()


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
    session._rtp_receiver.start_audio_sender.assert_called_once_with(
        123, session._send_audio_packet
    )
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
    session._rtp_receiver.start_audio_sender.assert_called_once_with(
        456, session._send_audio_packet
    )
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
async def test_microphone_audio_uses_panel_rtpc_tcp_channel() -> None:
    """PCMA microphone RTP follows the TCP media transport selected by the panel."""
    receiver = RtpReceiver("192.0.2.1")
    receiver._running = True
    receiver._backchannel_queue = asyncio.Queue()
    receiver._backchannel_queue.put_nowait(bytes([0xD5]) * 160)
    sent_packets: list[bytes] = []

    async def send_tcp(packet: bytes) -> None:
        sent_packets.append(packet)
        receiver._running = False

    receiver.start_audio_sender(0x1234, send_tcp)
    assert receiver._audio_sender_task is not None
    await receiver._audio_sender_task

    assert len(sent_packets) == 1
    assert len(sent_packets[0]) == 172
    assert sent_packets[0][0] >> 6 == 2
    assert sent_packets[0][1] & 0x7F == 8
    assert sent_packets[0][12:] == bytes([0xD5]) * 160


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
async def test_closed_device_rtpc_channel_renews_media_lease() -> None:
    """The panel's actual RTPC close renews even when CTPP status is ambiguous."""
    session = VideoCallSession.__new__(VideoCallSession)
    session._active = True
    session._ctpp_lock = asyncio.Lock()
    session._call_counter = 0
    session._device_rtpc_channel = Channel(
        name="RTPC_DEVICE",
        channel_type=ChannelType.UAUT,
        request_id=0,
        server_channel_id=0x1234,
        is_open=False,
    )
    client = MagicMock()

    async def renew(*_args: object) -> int:
        session._active = False
        return 43

    session._inline_reestablish = AsyncMock(side_effect=renew)

    await session._ctpp_monitor_loop(client, MagicMock(), "A1", "B1", 1, 2, 3)

    session._inline_reestablish.assert_awaited_once()
    assert session._call_counter == 43


@pytest.mark.asyncio
async def test_missing_media_is_a_start_failure() -> None:
    """A signaled call with no RTP is not exposed as a ready black stream."""
    receiver = MagicMock()
    receiver.wait_for_first_video = AsyncMock(side_effect=TimeoutError)
    receiver.udp_media_packet_count = 0
    receiver.tcp_media_packet_count = 0

    with pytest.raises(VideoCallError):
        await VideoCallSession._require_first_video(receiver)


@pytest.mark.asyncio
async def test_play_session_routes_interleaved_microphone_audio() -> None:
    """go2rtc's third SETUP track must feed the Comelit backchannel queue."""
    server = LocalRtspServer()
    writer = MagicMock()
    client = _TcpClient(writer=writer)
    transport = "RTP/AVP/TCP;unicast;interleaved=4-5"

    response = server._parse_setup(transport, "backchannel", client, "127.0.0.1")

    assert client.backchannel_ch == 4
    assert "interleaved=4-5" in response

    payload = b"\xd5" * 160
    rtp = struct.pack("!BBHII", 0x80, 8, 1, 160, 1234) + payload
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x24\x04" + struct.pack("!H", len(rtp)) + rtp)
    reader.feed_data(b"TEARDOWN rtsp://127.0.0.1/intercom RTSP/1.0\r\nCSeq: 4\r\n\r\n")
    reader.feed_eof()
    server._running = True

    await server._wait_for_teardown(reader, client, "127.0.0.1")

    assert server.backchannel_queue.get_nowait() == payload
    assert client.backchannel_started is True
