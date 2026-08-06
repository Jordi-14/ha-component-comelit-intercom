# Comelit Intercom for Home Assistant

[![CI](https://github.com/Jordi-14/ha-component-comelit-intercom/actions/workflows/ci.yaml/badge.svg)](https://github.com/Jordi-14/ha-component-comelit-intercom/actions/workflows/ci.yaml)
[![HACS Validation](https://github.com/Jordi-14/ha-component-comelit-intercom/actions/workflows/hacs.yaml/badge.svg)](https://github.com/Jordi-14/ha-component-comelit-intercom/actions/workflows/hacs.yaml)
[![GitHub Release](https://img.shields.io/github/v/release/Jordi-14/ha-component-comelit-intercom)](https://github.com/Jordi-14/ha-component-comelit-intercom/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.5%2B-41BDF5?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)

This is a native Home Assistant integration for Comelit intercom systems (using the ICONA Bridge protocol). It allows you to control your Comelit doors and compatible relay outputs directly from Home Assistant without requiring MQTT or Docker containers.

## Features

- Direct TCP communication with Comelit intercom devices (no MQTT bridge needed)
- **Automatic token extraction** - no manual token retrieval required (if using default password)
- Automatic discovery of all available doors and compatible relay/actuator controls
- Creates button entities for each door and compatible relay/actuator control
- **Live intercom video in Home Assistant** through a local H.264/RTSP relay
- Doorbell, missed-call, door-opened, and interrupted-call event entity
- Two-way audio through a bundled WebRTC card
- Separate exterior-audio and microphone mute controls for browsers and the Home Assistant Companion app
- An explicit notification when another client takes over the call
- Simple configuration through Home Assistant UI
- Works with Comelit intercom models that support the ICONA Bridge protocol

## Requirements

- Home Assistant 2026.5.0 or newer
- Comelit intercom with WiFi connectivity (e.g., Comelit 6741W, 6721W)
- Comelit device IP address
- Device must be accessible on port 64100 (ICONA Bridge) and port 8080 (web interface for token extraction)

## Installation

### HACS Installation (recommended)

1. Ensure you have [HACS](https://hacs.xyz/) installed and set up
2. Add this repository's URL, `https://github.com/Jordi-14/ha-component-comelit-intercom`, as custom repository and select "Integration" (see [docs](https://hacs.xyz/docs/faq/custom_repositories/))
3. Search for "Comelit Intercom" and click on "Download"
4. After this is complete, restart Home Assistant

HACS installs stable releases by default. To test a prerelease, enable beta
updates for this repository and select the desired version. See
[Beta Testing](docs/beta_testing.md) before installing a beta.

### Manual Installation

1. Copy the `custom_components/comelit_intercom` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

After you've installed the component on your system, it's time to set it up:

1. Go to Settings → Devices & Services
2. Click "Add Integration" and search for "Comelit Intercom"
3. Enter your device's IP address
4. Leave the token field empty for automatic extraction, or provide your token if you know it

### Automatic Token Extraction

The integration can automatically extract your authentication token if your device uses the default 'comelit' password. Here's how it works:

1. Logs into your device's web interface (port 8080) using the default password
2. Creates a new configuration backup on the device
3. Downloads the most recent backup file
4. Extracts and parses the `users.cfg` file from the backup archive
5. Finds your authentication token using the pattern `9:4:"<token>"`

This process takes about 10-30 seconds and happens automatically during setup.

### Manual Token Extraction

If automatic extraction fails (e.g., you've changed the default password), you'll need to obtain the token manually. Follow the excellent guide by madchicken:
https://github.com/madchicken/comelit-client/wiki/Get-your-user-token-for-ICONA-Bridge

## Usage

After configuration, the integration will:
1. Connect to your Comelit device
2. Authenticate using your token
3. Discover all available doors and compatible relay/actuator controls
4. Create a button entity for each discovered control (e.g., `button.comelit_front_door_unlatch`)

You can then:
- Add door buttons to your dashboard
- Open the `Live feed` camera for an on-demand, receive-only camera view
- Enable an exterior audio call and independently mute or unmute your microphone
- Create automations to open doors based on events
- Use with voice assistants ("Hey Google, press the front door button")
- Include in scripts and scenes
- Trigger from presence detection, NFC tags, etc.

### Intercom card

The integration installs `custom:comelit-intercom-card`. Add a Manual card and
select the entities created for your Comelit device:

```yaml
type: custom:comelit-intercom-card
entity: camera.comelit_intercom_live_feed
call_entity: switch.comelit_intercom_exterior_audio
door_entities:
  - button.comelit_intercom_front_door
  - button.comelit_intercom_gate
```

Opening the card prefers the bundled low-latency WebRTC path and falls back
automatically to authenticated HLS when the browser or Companion app cannot
establish a WebRTC media route. The call toggle enables or ends exterior audio.
A new call starts with the microphone on, matching the Comelit app, and the
microphone button can mute it independently. If a Companion app local URL is
HTTP, call mode and exterior audio remain available but the microphone is marked
unavailable. Microphone transmission requires a secure URL. Two-way audio also
requires a working WebRTC route to Home Assistant (local access or a TURN relay
when the HTTPS endpoint is behind an HTTP-only tunnel).

Video lifecycle is automatic: opening the card starts an outbound view, ending
exterior audio restores a receive-only view, and an incoming ring is handled by
the persistent call listener. The diagnostic Start/Stop entities are not needed
for normal dashboard use.

## How It Works

### Protocol Overview

The Comelit ICONA Bridge uses a custom binary/JSON hybrid protocol over TCP port 64100. This integration implements the protocol natively in Python.

#### Message Structure

All messages have an 8-byte header followed by a variable-length body:

```
Header (8 bytes):
[0x00, 0x06]     - Magic bytes (constant)
[XX, XX]         - Body length (uint16, little endian)
[RR, RR]         - Request ID (uint16, little endian)
[0x00, 0x00]     - Padding

Body:
- JSON messages: Start with '{' (0x7b)
- Binary messages: Custom format based on message type
```

#### Channel-Based Communication

The protocol uses channels for different operations:
- **UAUT**: Authentication channel
- **UCFG**: Configuration channel (get door list)
- **CTPP**: Control channel (open doors)
- **INFO**: Server information
- **PUSH**: Push notifications

Each operation follows this pattern:
1. Open channel with COMMAND message (0xabcd)
2. Perform operations on the channel
3. Close channel with END message (0x01ef)

#### Door Opening Sequence

Opening a door involves:
1. Open CTPP channel with the apartment address
2. Send initialization message (0x18c0) with door parameters
3. Send open door command (0x1800)
4. Send open door confirmation (0x1820)

The binary messages contain apartment addresses, output indices, and specific byte patterns that the device expects.

### Architecture

The integration consists of:
- **comelit_client.py**: Python implementation of the ICONA Bridge protocol
- **token_extractor.py**: Automatic token extraction from device backups
- **config_flow.py**: UI configuration flow with automatic token extraction
- **coordinator.py**: Data update coordinator for efficient polling
- **button.py**: Button entities for door control
- **camera.py**: Home Assistant camera entity backed by the local RTSP relay
- **video/**: Outbound call signaling, RTP reception, H.264 decoding, and RTSP serving

### Live Video Flow

The built-in entrance camera is not an always-on RTSP endpoint. Starting the
feed negotiates a local ICONA video call, receives H.264 RTP packets from the
intercom, and exposes them to Home Assistant at a loopback RTSP URL. No Comelit
cloud service is used.

The video signaling is based on the PCAP-verified implementation from
[`antoiba86/hass-comelit-intercom-local`](https://github.com/antoiba86/hass-comelit-intercom-local),
with additional research from its actively maintained
[`mnestrud/comelit-man`](https://github.com/mnestrud/comelit-man) fork. It has
been proven on the Comelit 6701W and uses the same ICONA Bridge channels used by
this integration. The outbound video path has been verified on the Comelit
6741W. Firmware behavior can still vary on other models.

### Call and audio behavior

Comelit permits only one client to own a call. If the Comelit mobile app takes
over while Home Assistant is viewing, the camera records a `last_end_reason`,
fires a `call_ended` event, and creates a persistent notification explaining the
likely cause.

Audio is kept separate from video, matching the Comelit app: viewing the camera
does not by itself enable the exterior audio path. Audio behavior can vary by
model and firmware; this beta targets the verified 6741W setup while retaining
the inbound signaling path learned from other ICONA Bridge devices.

## Credits

This integration was made possible thanks to:

- **[madchicken's comelit-client](https://github.com/madchicken/comelit-client)** - The original Node.js implementation that we reverse-engineered to understand the protocol, especially:
  - The ICONA Bridge protocol documentation
  - The binary message structure for door operations
  - The channel management system
  - Token extraction methodology

- **[antoiba86's hass-comelit-intercom-local](https://github.com/antoiba86/hass-comelit-intercom-local)** - Apache-2.0-licensed local video signaling, RTP, and RTSP implementation used by the camera feature

- **[mnestrud's comelit-man](https://github.com/mnestrud/comelit-man)** - Continued maintenance, compatibility work, and live-device video validation

- **[cmos486's Ring Intercom Video Card](https://github.com/cmos486/ring-intercom-video-card)** - Apache-2.0-licensed WebRTC microphone and browser/Companion app signaling pattern used by the bundled card

- **Protocol Reverse Engineering** - The complex binary protocol for door operations was decoded by analyzing the comelit-client implementation, particularly:
  - The specific byte patterns required for door commands (0x18c0, 0x1800, 0x1820)
  - The message structure with apartment addresses and output indices
  - The proper sequence of initialization and confirmation messages

## Troubleshooting

### Cannot Connect
- Verify the IP address is correct
- Ensure the device is on the same network as Home Assistant
- Check that ports 64100 (ICONA Bridge) and 8080 (web interface) are accessible
- Check Home Assistant logs for detailed error messages

### Token Extraction Failed
- Verify your device uses the default 'comelit' password
- Try extracting the token manually (see link above)
- Ensure port 8080 is accessible for the web interface
- Check if your device creates encrypted backups (some firmware versions)

### Invalid Authentication
- Token may have changed (regenerate if needed)
- Device might have been reset
- Try the automatic extraction again

### Controls Not Appearing
- Check that doors are configured in your Comelit mobile app first
- Verify the device config contains door or actuator entries
- Check logs for configuration data

### Known Issues
- Some Comelit devices may have encrypted backups, preventing automatic token extraction
- Connection issues on macOS with Python 3.13 (being investigated)
- Very old firmware versions may use a different protocol
- Only one ICONA operation runs at a time; configuration polling pauses while video is active
- Only one app can own the Comelit call at a time
- Two-way-audio behavior may vary between ICONA Bridge models and firmware versions
- Browser microphone access requires HTTPS
- Two-way audio requires direct WebRTC reachability or a configured TURN relay;
  receive-only HLS video continues to work through HTTP-only remote tunnels

## Developer Information

### Protocol Implementation

The Python implementation handles:
- Binary/JSON message encoding/decoding
- Channel lifecycle management with proper IDs
- Timeout handling for unreliable device responses
- Proper byte alignment and null termination
- Request ID tracking

For protocol analysis tools and captures, see the original comelit-client repository.

## License

This project is licensed under the GPL-3.0 License. The derived video transport
under `custom_components/comelit_intercom/video` retains its Apache-2.0 license.

## Disclaimer

This integration is not affiliated with or endorsed by Comelit Group S.p.A. It's a community project based on reverse engineering efforts.

**Note**: This integration is specifically for Comelit intercom systems. For Comelit SimpleHome alarm systems, use the [official Comelit integration](https://www.home-assistant.io/integrations/comelit/).
