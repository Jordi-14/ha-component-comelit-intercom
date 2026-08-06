# Beta Testing

Beta releases are intended for deliberate testing of camera, call signaling,
audio, event, and dashboard behavior before a stable release.

## Install a beta

Every prerelease includes a HACS-compatible `comelit_intercom.zip` asset.

### Through HACS

1. Open the Comelit Intercom repository in HACS.
2. Enable prerelease or beta updates from the repository menu.
3. Redownload the repository and select the desired beta version.
4. Restart Home Assistant.
5. Confirm the loaded version before testing the intercom.

The exact menu labels can vary between HACS versions. Disable prerelease updates
again if the installation should return to the stable channel after testing.

### Manually

1. Download `comelit_intercom.zip` from the selected
   [GitHub prerelease](https://github.com/Jordi-14/ha-component-comelit-intercom/releases).
2. Create a full Home Assistant backup.
3. Replace the contents of `custom_components/comelit_intercom` with the files
   from the ZIP.
4. Restart Home Assistant and confirm the loaded version.

Do not mix files from different releases.

## Test checklist

- Existing door entities and entity IDs remain unchanged.
- Every configured door has a separate working button.
- Opening the bundled card starts video without enabling exterior audio.
- Receive-only video works in browsers and the Companion app through HA's HLS
  path, including through HTTP-only remote tunnels.
- The exterior-audio switch enables and ends the audio call.
- The microphone starts muted and its toggle works in both a browser and the
  Home Assistant Companion app.
- When testing two-way audio remotely, Home Assistant must have a reachable
  WebRTC path (for example a TURN relay); an HTTP-only tunnel carries HLS but
  cannot carry the WebRTC media connection.
- A doorbell press creates a `ring` event and makes the inbound video available.
- Opening the Comelit app during an HA session ends the HA stream with a clear
  `call_ended` event and notification.
- Door controls still work during and outside an active video session.

Keep the entrance visible and the official Comelit app available while testing
call or relay behavior.

## Report a beta problem

Include the beta version, Home Assistant version, Comelit model and firmware,
whether testing in a browser or Companion app, and the expected and observed
behavior. Review logs and diagnostics before publishing them; do not share
tokens, local IP addresses, backups, databases, or packet captures publicly.

## Roll back

Restore the full Home Assistant backup created before testing, or reinstall the
previous integration version in HACS and restart Home Assistant. A full backup
is preferred because it also preserves config-entry state.
