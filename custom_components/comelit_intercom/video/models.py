"""Data models for Comelit device configuration and events."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Door:
    """A door or gate that can be opened."""

    id: int
    index: int
    name: str
    apt_address: str
    output_index: int
    secure_mode: bool = False
    is_actuator: bool = False
    module_index: int = 0


@dataclass
class Camera:
    """An RTSP camera discovered from device config."""

    id: int
    name: str
    rtsp_url: str
    rtsp_user: str = ""
    rtsp_password: str = ""


@dataclass
class DeviceConfig:
    """Parsed device configuration."""

    apt_address: str = ""
    apt_subaddress: int = 0
    caller_address: str = ""  # from entrance-address-book (app/indoor unit address)
    doors: list[Door] = field(default_factory=list)
    cameras: list[Camera] = field(default_factory=list)
    raw: dict | None = None


@dataclass
class PushEvent:
    """A push notification event (e.g. doorbell ring)."""

    event_type: str
    apt_address: str = ""
    timestamp: float = 0.0
    raw: dict | None = None
