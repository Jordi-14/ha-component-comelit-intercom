# Changelog

## 1.4.0

- Keep the integration camera-focused: doorbell rings no longer answer or
  control video sessions, and no call or audio controls are exposed.
- Track simultaneous WebRTC viewers independently so closing one card cannot
  stop another viewer's feed.
- Fix stale dashboard tasks that could start live video after previews were
  disabled or the card was hidden.
- Restore pre-camera door entity identities and migrate the short-lived v1.3
  beta IDs without changing entity IDs.
- Accept singleton door and actuator address books returned by older firmware.
- Add stable device identification, a configurable protocol port,
  reauthentication, and IP-address reconfiguration.
- Use Home Assistant config-entry runtime data and create the camera even when
  the device exposes no door controls.
- Harden automatic token extraction against oversized downloads and archive
  expansion.
- Align dependencies, typing, tests, and CI with Home Assistant 2026.5 and
  Python 3.14.

## 1.3.0

- Add an `Automatic still previews` switch, disabled by default.
- Add a 0–180 minute `Still preview interval` setting in 0.5-minute steps.
- Add a privacy-aware dashboard card that only refreshes while visible.
- Treat an interval of 0 as live video while the card is visible.
- Show the local capture time on every still and open live video when clicked.
- Preserve the released 1.2.0 camera, door, and media-session architecture.
