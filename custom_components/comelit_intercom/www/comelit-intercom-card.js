/**
 * Comelit Intercom Card
 * SPDX-License-Identifier: Apache-2.0
 * WebRTC microphone flow adapted from cmos486/ring-intercom-video-card.
 */

const CARD_TAG = "comelit-intercom-card";

class ComelitIntercomCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pc = null;
    this._mic = null;
    this._sessionId = null;
    this._pendingCandidates = [];
    this._connected = false;
    this._micEnabled = false;
    this._nativeStream = null;
    this._mountingNativeStream = false;
    this._failureReason = null;
    this._videoLoaded = false;
    this._connectionTimer = null;
    this._nativeFallbackTimer = null;
  }

  static getStubConfig() {
    return { entity: "camera.comelit_intercom_live_feed" };
  }

  setConfig(config) {
    if (!config.entity) throw new Error("A Comelit camera entity is required");
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const camera = this._cameraState();
    const video = this.shadowRoot?.getElementById("call-video");
    if (video && camera?.attributes?.access_token) {
      video.poster = `/api/camera_proxy/${this._config.entity}?token=${camera.attributes.access_token}`;
    }
    if (this._nativeStream) {
      this._nativeStream.hass = hass;
    }
    this._refreshIdleState();
    if (this._config && !this._pc) {
      queueMicrotask(() => this._ensureNativeStream());
    }
  }

  getCardSize() {
    return 5;
  }

  _render() {
    const doors = this._config.door_entities ||
      (this._config.door_entity ? [this._config.door_entity] : []);
    const doorButtons = doors.map((entity, index) =>
      `<button class="door" data-entity="${entity}">OPEN ${index + 1}</button>`,
    ).join("");
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { overflow: hidden; }
        .video { position: relative; aspect-ratio: 5 / 3; background: #000; }
        #native-stream, #native-stream > * { width: 100%; height: 100%; display: block; }
        #native-stream > * { --video-max-height: 100%; }
        #call-video { width: 100%; height: 100%; object-fit: contain; }
        [hidden] { display: none !important; }
        audio { display: none; }
        .status { position: absolute; left: 10px; bottom: 10px; max-width: calc(100% - 36px);
          color: white; background: rgba(0,0,0,.7); border-radius: 6px; padding: 6px 8px;
          font-size: 12px; }
        .controls { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; padding: 14px; }
        button { min-height: 48px; border: 0; border-radius: 10px; color: white;
          font-size: 14px; font-weight: 600; cursor: pointer; touch-action: none; }
        button:disabled { opacity: .4; cursor: default; }
        #connect { background: #008f5a; }
        #connect.active { background: #c62828; }
        #mic { background: #555; }
        #mic.active { background: #008f5a; }
        .door { background: #ef6c00; }
      </style>
      <ha-card>
        <div class="video">
          <div id="native-stream"></div>
          <video id="call-video" autoplay playsinline muted hidden></video>
          <audio autoplay playsinline muted></audio>
          <div class="status">Connecting video…</div>
        </div>
        <div class="controls">
          <button id="connect">START CALL</button>
          <button id="mic" disabled title="Available after the video connection is established">MIC MUTED</button>
          ${doorButtons}
        </div>
      </ha-card>`;

    this.shadowRoot.getElementById("connect").onclick = () => this._toggleCall();
    this.shadowRoot.getElementById("mic").onclick = () =>
      this._setMic(!this._micEnabled);
    this.shadowRoot.querySelectorAll(".door").forEach((button) => {
      button.onclick = () => this._press(button.dataset.entity);
    });
  }

  _cameraState() {
    return this._hass?.states?.[this._config.entity];
  }

  async _ensureNativeStream() {
    if (
      !this.isConnected || !this._hass || !this._config || this._pc ||
      this._nativeStream || this._mountingNativeStream
    ) return;

    this._mountingNativeStream = true;
    try {
      // Prefer HA's official WebRTC player for low-latency viewing. If the
      // current browser/app cannot establish a media route, switch to HLS on
      // HA's authenticated HTTP path instead of leaving a black player.
      if (!window.loadCardHelpers) {
        throw new Error("Home Assistant's card helpers are unavailable");
      }
      const helpers = await window.loadCardHelpers();
      const container = this.shadowRoot?.getElementById("native-stream");
      if (!container) return;
      // Creating (but not mounting) HA's picture card loads the camera-player
      // modules on frontend versions where the players are lazy-loaded.
      await helpers.createCardElement({
        type: "picture-entity",
        entity: this._config.entity,
      });
      await Promise.all([
        customElements.whenDefined("ha-web-rtc-player"),
        customElements.whenDefined("ha-hls-player"),
      ]);
      const stream = document.createElement("ha-web-rtc-player");
      stream.hass = this._hass;
      stream.entityid = this._config.entity;
      stream.autoPlay = true;
      stream.playsInline = true;
      stream.muted = true;
      stream.addEventListener("load", () => {
        clearTimeout(this._nativeFallbackTimer);
        this._nativeFallbackTimer = null;
        this._status(this._failureReason || "Live");
      });
      stream.addEventListener("streams", (event) => {
        if (event.detail?.hasVideo === false) {
          this._mountHlsStream("WebRTC unavailable; using compatible live video…");
        } else if (event.detail?.hasVideo) {
          clearTimeout(this._nativeFallbackTimer);
          this._nativeFallbackTimer = null;
          this._status(this._failureReason || "Live");
        }
      });
      container.replaceChildren(stream);
      this._nativeStream = stream;
      this._nativeFallbackTimer = setTimeout(() => {
        if (this._nativeStream === stream && !this._pc) {
          this._mountHlsStream("WebRTC unavailable; using compatible live video…");
        }
      }, 8000);
      if (!this._failureReason) this._status("Connecting video…");
    } catch (error) {
      this._status(error.message || "Unable to load Home Assistant's camera player");
    } finally {
      this._mountingNativeStream = false;
    }
  }

  _mountHlsStream(statusText) {
    if (!this._hass || !this._config || this._pc) return;
    const container = this.shadowRoot?.getElementById("native-stream");
    if (!container) return;
    clearTimeout(this._nativeFallbackTimer);
    this._nativeFallbackTimer = null;
    const stream = document.createElement("ha-hls-player");
    stream.hass = this._hass;
    stream.entityid = this._config.entity;
    stream.autoPlay = true;
    stream.playsInline = true;
    stream.muted = true;
    stream.allowExoPlayer = true;
    stream.addEventListener("load", () => {
      this._status(this._failureReason || "Live (compatible mode)");
    });
    stream.addEventListener("streams", (event) => {
      if (event.detail?.hasVideo === false) {
        this._status("Live video unavailable; showing the latest image");
      }
    });
    container.replaceChildren(stream);
    this._nativeStream = stream;
    if (statusText) this._status(statusText);
  }

  _removeNativeStream() {
    clearTimeout(this._nativeFallbackTimer);
    this._nativeFallbackTimer = null;
    this._nativeStream?.remove();
    this._nativeStream = null;
    const container = this.shadowRoot?.getElementById("native-stream");
    if (container) container.replaceChildren();
  }

  _showCallVideo(show) {
    const video = this.shadowRoot?.getElementById("call-video");
    if (video) video.hidden = !show;
    const native = this.shadowRoot?.getElementById("native-stream");
    if (native) native.hidden = show;
  }

  _isInbound() {
    return this._cameraState()?.attributes?.call_direction === "inbound";
  }

  _refreshIdleState() {
    if (!this.shadowRoot || this._connected || this._pc) return;
    if (this._failureReason) {
      this._status(this._failureReason);
      return;
    }
    const state = this._cameraState();
    const connect = this.shadowRoot.getElementById("connect");
    if (connect) connect.textContent = this._isInbound() ? "ANSWER CALL" : "START CALL";
    const reason = state?.attributes?.last_end_reason;
    if (reason) this._status(reason);
  }

  _status(text) {
    const status = this.shadowRoot?.querySelector(".status");
    if (status) status.textContent = text;
  }

  async _press(entityId) {
    if (!entityId) return;
    await this._hass.callService("button", "press", { entity_id: entityId });
  }

  async _setCall(enabled) {
    if (this._config.call_entity) {
      await this._hass.callService("switch", enabled ? "turn_on" : "turn_off", {
        entity_id: this._config.call_entity,
      });
    } else if (enabled && this._config.answer_entity) {
      await this._press(this._config.answer_entity);
    }
  }

  async _toggleCall() {
    const wasAudioCall = Boolean(this._mic);
    this._teardown(false, false);
    try {
      if (wasAudioCall) {
        this._status("Restoring video…");
        // The service now returns only after the old device channels are
        // released and a fresh receive-only Comelit session is ready.
        await this._setCall(false);
        this._showCallVideo(false);
        await this._ensureNativeStream();
      } else {
        this._removeNativeStream();
        this._showCallVideo(true);
        await this._connect();
      }
    } catch (error) {
      await this._fail(error.message || "Unable to change the intercom call state.");
    }
  }

  async _connect() {
    if (this._pc) return;
    this._failureReason = null;
    const connect = this.shadowRoot.getElementById("connect");
    connect.disabled = true;
    this._status("Requesting microphone…");

    try {
      const speaker = this.shadowRoot.querySelector("audio");
      speaker.muted = false;
      speaker.play().catch(() => {});

      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("Microphone access requires an HTTPS Home Assistant URL");
      }
      this._mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      this._mic.getAudioTracks().forEach((track) => { track.enabled = false; });
      await this._setCall(true);

      // Use the same ICE/server configuration as Home Assistant's native
      // camera player. This is important for both browsers and companion apps,
      // where the media route can differ from the WebSocket route to HA.
      const clientConfig = await this._hass.callWS({
        type: "camera/webrtc/get_client_config",
        entity_id: this._config.entity,
      });
      this._pc = new RTCPeerConnection(clientConfig.configuration);
      if (clientConfig.dataChannel) {
        this._pc.createDataChannel(clientConfig.dataChannel);
      }
      const track = this._mic.getAudioTracks()[0];
      this._pc.addTransceiver(track, { direction: "sendrecv", streams: [this._mic] });
      this._pc.addTransceiver("video", { direction: "recvonly" });
      this._pc.ontrack = (event) => {
        const video = this.shadowRoot.getElementById("call-video");
        const audio = this.shadowRoot.querySelector("audio");
        const media = event.track.kind === "video" ? video : audio;
        if (!media.srcObject) media.srcObject = new MediaStream();
        media.srcObject.addTrack(event.track);

        if (event.track.kind === "video") {
          this._status("Receiving video…");
          video.muted = true;
          video.play().catch(() => {
            this._status("Tap the video to start playback");
          });
        } else {
          audio.muted = false;
          audio.play().catch(() => {
            this._status("Tap the video to enable exterior audio");
          });
        }
      };
      const video = this.shadowRoot.getElementById("call-video");
      video.onloadeddata = () => {
        this._videoLoaded = true;
        this._status("Live");
      };
      video.onclick = () => {
        video.play().catch(() => {});
        const audio = this.shadowRoot.querySelector("audio");
        if (!audio.muted) audio.play().catch(() => {});
      };
      this._pc.onconnectionstatechange = async () => {
        if (!this._pc) return;
        this._status(this._pc.connectionState);
        if (this._pc.connectionState === "connected") {
          clearTimeout(this._connectionTimer);
          this._connectionTimer = null;
          this._connected = true;
          const call = this.shadowRoot.getElementById("connect");
          call.disabled = false;
          call.textContent = "END CALL";
          call.classList.add("active");
          const mic = this.shadowRoot.getElementById("mic");
          mic.disabled = false;
          mic.title = "Mute or unmute your microphone";
        } else if (this._pc.connectionState === "failed") {
          await this._fail(
            "Two-way audio could not establish a WebRTC route. Live video has been restored.",
          );
        }
      };
      this._pc.oniceconnectionstatechange = () => {
        if (this._pc?.iceConnectionState === "failed") {
          this._status("The call connection failed; restoring live video…");
        }
      };
      this._pc.onicecandidate = async (event) => {
        if (!event.candidate?.candidate) return;
        // Preserve usernameFragment and every browser-specific candidate
        // field exactly as HA's native player does.
        const candidate = event.candidate.toJSON();
        if (!this._sessionId) this._pendingCandidates.push(candidate);
        else await this._sendCandidate(candidate);
      };

      const offer = await this._pc.createOffer({
        offerToReceiveAudio: true,
        offerToReceiveVideo: true,
      });
      await this._pc.setLocalDescription(offer);
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (message) => this._onSignal(message),
        {
          type: "camera/webrtc/offer",
          entity_id: this._config.entity,
          offer: offer.sdp,
        },
      );
      this._connectionTimer = setTimeout(() => {
        if (!this._connected && this._pc) {
          this._fail(
            "Two-way audio needs a direct WebRTC route to Home Assistant. " +
            "Live video has been restored; retry on the local network or through a TURN relay.",
          );
        }
      }, 12000);
    } catch (error) {
      await this._fail(error.message || "Unable to start the intercom session.");
    }
  }

  async _sendCandidate(candidate) {
    if (!this._sessionId) return;
    await this._hass.connection.sendMessagePromise({
      type: "camera/webrtc/candidate",
      entity_id: this._config.entity,
      session_id: this._sessionId,
      candidate,
    });
  }

  async _onSignal(message) {
    if (message.type === "session") {
      this._sessionId = message.session_id;
      for (const candidate of this._pendingCandidates.splice(0)) {
        await this._sendCandidate(candidate);
      }
    } else if (message.type === "answer") {
      await this._pc.setRemoteDescription({ type: "answer", sdp: message.answer });
    } else if (message.type === "candidate") {
      const candidate = message.candidate.sdpMid ||
        message.candidate.sdpMLineIndex != null
        ? message.candidate
        : { ...message.candidate, sdpMid: "0" };
      await this._pc.addIceCandidate(candidate);
    } else if (message.type === "error") {
      await this._fail(message.message || message.code || "Unable to start the video stream.");
    }
  }

  async _fail(reason) {
    const hadAudio = Boolean(this._mic);
    this._failureReason = reason;
    this._teardown(false, false);
    this._status(reason);
    if (hadAudio) {
      try {
        await this._setCall(false);
      } catch (_error) {
        // Preserve the original WebRTC failure; the backend log has rollback details.
      }
      this._status(reason);
    }
    this._showCallVideo(false);
    await this._ensureNativeStream();
  }

  _setMic(enabled) {
    if (!this._connected || !this._mic) return;
    this._mic.getAudioTracks().forEach((track) => { track.enabled = enabled; });
    this._micEnabled = enabled;
    const mic = this.shadowRoot.getElementById("mic");
    mic.textContent = enabled ? "MIC ON" : "MIC MUTED";
    mic.classList.toggle("active", enabled);
  }

  _teardown(setIdle = true, restoreNative = true) {
    this._connected = false;
    this._micEnabled = false;
    this._videoLoaded = false;
    const video = this.shadowRoot?.getElementById("call-video");
    if (video?.srcObject) {
      video.srcObject.getTracks().forEach((track) => track.stop());
      video.srcObject = null;
    }
    const audio = this.shadowRoot?.querySelector("audio");
    if (audio?.srcObject) {
      audio.srcObject.getTracks().forEach((track) => track.stop());
      audio.srcObject = null;
    }
    if (audio) audio.muted = true;
    if (this._unsubscribe) this._unsubscribe();
    this._unsubscribe = null;
    const pc = this._pc;
    this._pc = null;
    if (pc) pc.close();
    if (this._mic) this._mic.getTracks().forEach((track) => track.stop());
    this._mic = null;
    this._sessionId = null;
    this._pendingCandidates = [];
    clearTimeout(this._connectionTimer);
    this._connectionTimer = null;
    const mic = this.shadowRoot?.getElementById("mic");
    if (mic) {
      mic.disabled = true;
      mic.textContent = "MIC MUTED";
      mic.title = "Available after the video connection is established";
      mic.classList.remove("active");
    }
    const connect = this.shadowRoot?.getElementById("connect");
    if (connect) {
      connect.disabled = false;
      connect.textContent = this._isInbound() ? "ANSWER CALL" : "START CALL";
      connect.classList.remove("active");
    }
    if (setIdle) {
      this._failureReason = null;
      this._status("Connecting video…");
    }
    this._showCallVideo(false);
    if (restoreNative) queueMicrotask(() => this._ensureNativeStream());
  }

  disconnectedCallback() {
    this._removeNativeStream();
    this._teardown(false, false);
  }
}

customElements.define(CARD_TAG, ComelitIntercomCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "Comelit Intercom Card",
  description: "Video, exterior audio, microphone, and door controls for Comelit intercoms",
});
