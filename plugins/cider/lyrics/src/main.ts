import {
  addMainMenuEntry,
  definePluginContext,
} from "@ciderapp/pluginkit";

import { createProbePayload } from "./probe/payload";
import { probePlayback } from "./probe/playback";
import { dedupeBrowserAppliedPluginList } from "./probe/pluginState";
import { ReconnectingLyricsSocket, frameSignature } from "./probe/transport";
import type { AdapterClock, FrameReason, ProbeConfig } from "./probe/types";
import PluginConfig from "./plugin.config";

const DEFAULT_CONFIG: ProbeConfig = {
  endpoint: "ws://127.0.0.1:28745/kotonoha/adapter",
  pollMs: 200,
  heartbeatMs: 1000,
  tickMs: 100,
  consoleLog: false,
};

let pollId: number | undefined;
let tickId: number | undefined;
let socket: ReconnectingLyricsSocket | undefined;

// Change-detection / heartbeat bookkeeping.
let lastSignature: string | null = null;
let lastSentAt = 0;
let building = false;
let messageSequence = 0;

const { plugin, setupConfig, customElementName, goToPage, useCPlugin } =
  definePluginContext({
    ...PluginConfig,
    setup() {
      dedupeBrowserAppliedPluginList(PluginConfig.identifier);

      addMainMenuEntry({
        label: "Lyrics Probe: send snapshot",
        onClick() {
          void pushFrame("manual");
        },
      });

      startSocket();
      startProbeLoop();
      startTickLoop();
    },
  });

export const cfg = setupConfig(DEFAULT_CONFIG);

function currentConfig(): ProbeConfig {
  return {
    ...DEFAULT_CONFIG,
    ...(cfg.value ?? {}),
  };
}

function log(message: string, error?: unknown) {
  if (currentConfig().consoleLog) {
    if (error !== undefined) {
      console.warn("[kotonoha-cider-lyrics]", message, error);
    } else {
      console.log("[kotonoha-cider-lyrics]", message);
    }
  }
}

function startSocket() {
  socket?.close();
  socket = new ReconnectingLyricsSocket({
    url: currentConfig().endpoint,
    log,
    // On every (re)connect, push a full snapshot immediately so the overlay is
    // never blank waiting for the next change.
    onOpen() {
      lastSignature = null;
      void pushFrame("open");
    },
  });
  socket.connect();
}

function startProbeLoop() {
  if (pollId !== undefined) {
    window.clearInterval(pollId);
  }
  const config = currentConfig();
  pollId = window.setInterval(() => {
    void tick();
  }, Math.max(50, config.pollMs));
}

// Lightweight high-frequency clock calibration: only the real playback head and
// status are sent. Kotonoha interpolates between these at display rate.
function startTickLoop() {
  if (tickId !== undefined) {
    window.clearInterval(tickId);
  }
  const config = currentConfig();
  tickId = window.setInterval(() => {
    if (socket === undefined || !socket.isOpen) {
      return;
    }
    const playback = probePlayback(window);
    if (playback.positionS === null) {
      return;
    }
    const message: AdapterClock = {
      protocol: "kotonoha.adapter",
      version: 1,
      type: "clock",
      adapter: "cider",
      sequence: ++messageSequence,
      capturedAt: new Date().toISOString(),
      trackRef:
        playback.track?.stableId === null || playback.track?.stableId === undefined
          ? null
          : `cider:cider:${playback.track.stableId}`,
      positionS: playback.positionS,
      status: playback.status,
    };
    socket.send(JSON.stringify(message));
  }, Math.max(30, config.tickMs));
}

/** How long one payload build may take before probing gives up on it. */
const BUILD_TIMEOUT_MS = 15_000;
/** Rises per replacement build so a late one cannot overwrite a newer frame. */
let buildGeneration = 0;

/** Build a payload, refusing to wait for one that never settles.
 *
 * `building` is held for the whole build, and a request that neither resolves nor
 * rejects left it held for ever: every later probe returned at the guard and the
 * overlay stopped receiving frames for the rest of the session, with nothing said.
 */
async function buildPayload(): Promise<Awaited<ReturnType<typeof createProbePayload>> | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), BUILD_TIMEOUT_MS);
  });
  try {
    const payload = await Promise.race([
      createProbePayload({
        globals: window,
        version: PluginConfig.version,
        sequence: ++messageSequence,
      }),
      deadline,
    ]);
    if (payload === null) {
      log(`payload build exceeded ${BUILD_TIMEOUT_MS}ms; dropping this probe`);
    }
    return payload;
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}

/** Sample Cider state; send only when the situation changed or a heartbeat is due. */
async function tick() {
  if (building || socket === undefined || !socket.isOpen) {
    return;
  }
  building = true;
  const generation = ++buildGeneration;
  try {
    const config = currentConfig();
    const payload = await buildPayload();
    if (payload === null || generation !== buildGeneration) {
      return;
    }
    const signature = frameSignature(payload);
    const now = Date.now();

    const changed = signature !== lastSignature;
    const heartbeatDue = now - lastSentAt >= config.heartbeatMs;
    if (!changed && !heartbeatDue) {
      return;
    }
    sendBuiltPayload(payload, changed ? "change" : "heartbeat", signature, now);
  } catch (error) {
    log("probe tick failed", error);
  } finally {
    building = false;
  }
}

/** Build + send a frame unconditionally (used for open/manual). */
async function pushFrame(reason: FrameReason) {
  if (socket === undefined) {
    return;
  }
  const generation = ++buildGeneration;
  try {
    const payload = await buildPayload();
    if (payload === null || generation !== buildGeneration) {
      // A newer build started while this one was in flight; sending now would put
      // the older track back on the overlay.
      return;
    }
    sendBuiltPayload(payload, reason, frameSignature(payload), Date.now());
  } catch (error) {
    log("pushFrame failed", error);
  }
}

function sendBuiltPayload(
  payload: Awaited<ReturnType<typeof createProbePayload>>,
  reason: FrameReason,
  signature: string,
  now: number,
) {
  log(`send ${reason}`);
  const sent = socket?.send(JSON.stringify(payload)) ?? false;
  if (sent) {
    lastSignature = signature;
    lastSentAt = now;
  }
}

export { setupConfig, customElementName, goToPage, useCPlugin };

export default plugin;
