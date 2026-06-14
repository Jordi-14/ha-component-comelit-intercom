# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant custom component for Comelit intercom systems (using the ICONA Bridge protocol). It provides native integration without requiring MQTT or Docker containers, allowing users to control their Comelit doors directly from Home Assistant.

**Note**: This integration is specifically for Comelit intercom systems. It's separate from the official Comelit integration which handles their SimpleHome alarm systems.

## Development Commands

### Testing the Integration
```bash
# Test the Python client library standalone
python3 custom_components/comelit_intercom/comelit_client.py

# Run Home Assistant with the custom component
hass -c /path/to/config
```

### Code Quality
```bash
# Format code with black
black custom_components/comelit_intercom/

# Check import order with isort
isort custom_components/comelit_intercom/

# Run Python linting with ruff
ruff check custom_components/comelit_intercom/

# Auto-fix linting issues
ruff check custom_components/comelit_intercom/ --fix

# Type checking
mypy custom_components/comelit_intercom/

# Run all checks (as done in CI)
black --check custom_components/comelit_intercom/
isort --check-only custom_components/comelit_intercom/
ruff check custom_components/comelit_intercom/
```

## Architecture

### Core Components

1. **comelit_client.py** - Low-level protocol implementation
   - Handles TCP socket communication on port 64100
   - Implements the binary/JSON hybrid protocol
   - Manages channel lifecycle (open/close)
   - Provides door listing and opening functionality
   - Contains detailed protocol comments explaining byte sequences

2. **token_extractor.py** - Automatic token extraction
   - Logs into device web interface (port 8080)
   - Uses IP-based sessions (no cookies needed)
   - Creates and downloads configuration backups
   - Extracts tokens from users.cfg files
   - Handles both plain and gzipped config files

3. **config_flow.py** - Home Assistant configuration UI
   - Implements the setup flow for the integration
   - Attempts automatic token extraction if none provided
   - Validates device connectivity and authentication
   - Stores configuration in Home Assistant

4. **coordinator.py** - Data update coordinator
   - Manages periodic updates from the device
   - Caches door list to reduce API calls
   - Handles connection failures gracefully
   - Implements Home Assistant's DataUpdateCoordinator pattern

5. **button.py** - Home Assistant button entities
   - Creates a button for each discovered door
   - Handles button press events to open doors
   - Updates availability based on coordinator status

### Protocol Details

#### Binary Protocol Structure

The Comelit ICONA Bridge uses a custom protocol with 8-byte headers:

```
Header: [0x00, 0x06] [LENGTH] [REQUEST_ID] [0x00, 0x00]
```

Key message types:
- `0xabcd` (COMMAND) - Opens a channel
- `0x01ef` (END) - Closes a channel
- `0x18c0` - Door initialization
- `0x1800` - Open door command
- `0x1820` - Open door confirmation

#### Channel Types

The protocol uses different channels for operations:
- **UAUT** (ID: 7) - Authentication
- **UCFG** (ID: 2) - Configuration retrieval
- **CTPP** (ID: 16) - Control operations (door opening)
- **INFO** (ID: 20) - Server information
- **PUSH** (ID: 2) - Push notifications

Note: These IDs differ from the ViperChannelType enum values in the original Node.js implementation.

#### Authentication Flow

1. Open UAUT channel
2. Send JSON message with token
3. Receive response with status code (200 = success)
4. Close channel

#### Door Discovery Flow

1. Authenticate
2. Open UCFG channel
3. Send get-configuration request
4. Parse VIP configuration for door list
5. Close channel

#### Door Opening Sequence

1. Open CTPP channel with apartment address
2. Send initialization message (0x18c0)
3. Send open door command (0x1800)
4. Send confirmation (0x1820)
5. Send door-specific initialization
6. Repeat open/confirm commands
7. Keep channel open for multiple operations

The redundancy in commands ensures reliability across firmware versions.

### Token Extraction Process

1. **Login**: POST to `/do-login.html` with password
   - Uses IP-based sessions (no cookie handling needed)
   - Default password: "comelit"

2. **Create Backup**: POST to `/create-backup.html`
   - Creates new backup with current configuration
   - Ensures we get the latest token

3. **Download**: GET `/{timestamp}.tar.gz`
   - Downloads the most recent backup file

4. **Extract Token**: Parse `users.cfg`
   - Look for pattern: `9:4:"[32-char-hex]"`
   - Field 9 contains the authentication token
   - Skip null tokens (all zeros)

### Error Handling

- **Connection Timeouts**: 10 seconds for initial connection
- **Response Timeouts**: 2 seconds for door operations (often timeout normally)
- **macOS Workaround**: Special handling for Python 3.13 socket issues
- **Graceful Degradation**: Continue operation even if some responses timeout

## Testing

### Manual Testing
1. Set environment variables:
   ```bash
   export COMELIT_IP_ADDRESS="192.168.1.100"
   export COMELIT_TOKEN="your_token_here"
   ```

2. Test the client:
   ```bash
   python3 custom_components/comelit/comelit_client.py
   ```

### Integration Testing
1. Copy component to HA custom_components directory
2. Restart Home Assistant
3. Add integration via UI
4. Check logs for any errors
5. Test door buttons

### Common Issues

- **Port 64100 Blocked**: Ensure firewall allows TCP connections
- **Wrong Token**: Token may change after device reset
- **Encrypted Backups**: Some firmware versions encrypt backups
- **Response Timeouts**: Normal for some operations, code handles gracefully

## Code Style Guidelines

- Use type hints for all function parameters and returns
- Add docstrings to all public methods
- Include inline comments for protocol-specific byte sequences
- Follow Home Assistant's code style for custom components
- Use meaningful variable names, especially for protocol constants

## Future Improvements

- Add sensor entities for door status
- Implement push notification support (PUSH channel)
- Add configuration options for timeouts
- Support for video intercom features
- Better error messages for common issues
- HACS repository structure

## Important Notes

- Never hardcode IP addresses or tokens in code
- Always handle connection failures gracefully
- The protocol is reverse-engineered and may change
- Test thoroughly with actual devices before releases
- Respect the original comelit-client project's GPL-3.0 license
