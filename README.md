# Comelit Intercom for Home Assistant

This is a native Home Assistant integration for Comelit intercom systems (using the ICONA Bridge protocol). It allows you to control your Comelit doors and compatible relay outputs directly from Home Assistant without requiring MQTT or Docker containers.

## Features

- Direct TCP communication with Comelit intercom devices (no MQTT bridge needed)
- **Automatic token extraction** - no manual token retrieval required (if using default password)
- Automatic discovery of all available doors and compatible relay/actuator controls
- Creates button entities for each door and compatible relay/actuator control
- Simple configuration through Home Assistant UI
- Works with Comelit intercom models that support the ICONA Bridge protocol

## Requirements

- Home Assistant 2023.1 or newer
- Comelit intercom with WiFi connectivity (e.g., Comelit 6741W, 6721W)
- Comelit device IP address
- Device must be accessible on port 64100 (ICONA Bridge) and port 8080 (web interface for token extraction)

## Installation

### HACS Installation (recommended)

1. Ensure you have [HACS](https://hacs.xyz/) installed and set up
2. Add this repository's URL, `https://github.com/nicolas-fricke/ha-component-comelit-intercom`, as custom repository and select "Integration" (see [docs](https://hacs.xyz/docs/faq/custom_repositories/))
3. Seach for "Comelit Intercom" and click on "Download"
4. After this is complete, restart Home Assistant

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
- Create automations to open doors based on events
- Use with voice assistants ("Hey Google, press the front door button")
- Include in scripts and scenes
- Trigger from presence detection, NFC tags, etc.

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

## Credits

This integration was made possible thanks to:

- **[madchicken's comelit-client](https://github.com/madchicken/comelit-client)** - The original Node.js implementation that we reverse-engineered to understand the protocol, especially:
  - The ICONA Bridge protocol documentation
  - The binary message structure for door operations
  - The channel management system
  - Token extraction methodology

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

This project is licensed under the GPL-3.0 License.

## Development Note

This integration was developed primarily using Claude Code (Anthropic's AI assistant). The entire codebase, including protocol reverse engineering, Python implementation, and Home Assistant integration, was written by Claude Code with supervision, testing, and high-level guidance from the maintainer. This approach allowed for rapid development of a complex integration that might have otherwise taken significantly longer to create manually.

## Disclaimer

This integration is not affiliated with or endorsed by Comelit Group S.p.A. It's a community project based on reverse engineering efforts.

**Note**: This integration is specifically for Comelit intercom systems. For Comelit SimpleHome alarm systems, use the [official Comelit integration](https://www.home-assistant.io/integrations/comelit/).
