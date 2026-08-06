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
    this._autoStarted = false;
    this._failureReason = null;
    this._videoLoaded = false;
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
    const video = this.shadowRoot?.querySelector("video");
    if (video && camera?.attributes?.access_token) {
      video.poster = `/api/camera_proxy/${this._config.entity}?token=${camera.attributes.access_token}`;
    }
    this._refreshIdleState();
    if (this._config && !this._autoStarted) {
      this._autoStarted = true;
      queueMicrotask(() => this._connect(false));
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
        .video { position: relative; aspect-ratio: 4 / 3; background: #000; }
        video { width: 100%; height: 100%; object-fit: contain; }
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
          <video autoplay playsinline muted></video>
          <audio autoplay playsinline muted></audio>
          <div class="status">Idle</div>
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
    this._teardown(false);
    try {
      if (wasAudioCall) {
        this._status("Restoring video…");
        // The service now returns only after the old device channels are
        // released and a fresh receive-only Comelit session is ready.
        await this._setCall(false);
        await this._connect(false);
      } else {
        await this._connect(true);
      }
    } catch (error) {
      await this._fail(error.message || "Unable to change the intercom call state.");
    }
  }

  async _connect(withAudio) {
    if (this._pc) return;
    this._failureReason = null;
    const connect = this.shadowRoot.getElementById("connect");
    connect.disabled = true;
    this._status(withAudio ? "Requesting microphone…" : "Connecting video…");

    try {
      const speaker = this.shadowRoot.querySelector("audio");
      speaker.muted = !withAudio;
      if (withAudio) speaker.play().catch(() => {});

      if (withAudio) {
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
          throw new Error("Microphone access requires an HTTPS Home Assistant URL");
        }
        this._mic = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          video: false,
        });
        this._mic.getAudioTracks().forEach((track) => { track.enabled = false; });
        await this._setCall(true);
      }

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
      if (this._mic) {
        const track = this._mic.getAudioTracks()[0];
        this._pc.addTransceiver(track, { direction: "sendrecv", streams: [this._mic] });
      } else {
        this._pc.addTransceiver("audio", { direction: "recvonly" });
      }
      this._pc.addTransceiver("video", { direction: "recvonly" });
      this._pc.ontrack = (event) => {
        const video = this.shadowRoot.querySelector("video");
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
        } else if (withAudio) {
          audio.muted = false;
          audio.play().catch(() => {
            this._status("Tap the video to enable exterior audio");
          });
        }
      };
      const video = this.shadowRoot.querySelector("video");
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
          this._connected = true;
          const call = this.shadowRoot.getElementById("connect");
          call.disabled = false;
          call.textContent = this._mic ? "END CALL" : "ENABLE AUDIO";
          call.classList.toggle("active", Boolean(this._mic));
          const mic = this.shadowRoot.getElementById("mic");
          mic.disabled = !this._mic;
          mic.title = this._mic ? "Mute or unmute your microphone" : "Enable exterior audio first";
        } else if (["failed", "closed"].includes(this._pc.connectionState)) {
          await this._fail(
            "The intercom ended this Home Assistant call. Another client, such as the Comelit app, may have taken control.",
          );
        }
      };
      this._pc.oniceconnectionstatechange = () => {
        if (this._pc?.iceConnectionState === "failed") {
          this._status("Reconnecting video…");
          this._pc.restartIce();
        }
      };
      this._pc.onicecandidate = async (event) => {
        if (!event.candidate?.candidate) return;
        const candidate = {
          candidate: event.candidate.candidate,
          sdpMid: event.candidate.sdpMid,
          sdpMLineIndex: event.candidate.sdpMLineIndex,
        };
        if (!this._sessionId) this._pendingCandidates.push(candidate);
        else await this._sendCandidate(candidate);
      };

      const offer = await this._pc.createOffer();
      await this._pc.setLocalDescription(offer);
      await new Promise((resolve) => setTimeout(resolve, 150));
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (message) => this._onSignal(message),
        {
          type: "camera/webrtc/offer",
          entity_id: this._config.entity,
          offer: this._pc.localDescription.sdp,
        },
      );
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
    this._teardown(false);
    this._status(reason);
    if (hadAudio) {
      try {
        await this._setCall(false);
      } catch (_error) {
        // Preserve the original WebRTC failure; the backend log has rollback details.
      }
      this._status(reason);
    }
  }

  _setMic(enabled) {
    if (!this._connected || !this._mic) return;
    this._mic.getAudioTracks().forEach((track) => { track.enabled = enabled; });
    this._micEnabled = enabled;
    const mic = this.shadowRoot.getElementById("mic");
    mic.textContent = enabled ? "MIC ON" : "MIC MUTED";
    mic.classList.toggle("active", enabled);
  }

  _teardown(setIdle = true) {
    this._connected = false;
    this._micEnabled = false;
    this._videoLoaded = false;
    const video = this.shadowRoot?.querySelector("video");
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
      this._status("Idle");
    }
  }

  disconnectedCallback() {
    this._teardown();
  }
}

customElements.define(CARD_TAG, ComelitIntercomCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "Comelit Intercom Card",
  description: "Video, exterior audio, microphone, and door controls for Comelit intercoms",
});
