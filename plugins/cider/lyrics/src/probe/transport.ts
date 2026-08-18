import type { ProbePayload } from "./types";

/** WebSocket.OPEN readyState value (spec-constant 1); avoids depending on a global WebSocket. */
const OPEN_READY_STATE = 1;

/**
 * A compact identity for a probe frame. Two frames with the same signature
 * describe the same lyric/playback situation, so we only need to push when the
 * signature changes (plus a periodic heartbeat for clock drift).
 *
 * Pure and side-effect free so it can be unit tested without a socket.
 */
export function frameSignature(payload: Pick<ProbePayload, "lyrics" | "playback">): string {
  const lyrics = payload.lyrics;
  const playing = payload.playback?.isPlaying ? "1" : "0";
  return [
    lyrics?.found ? "1" : "0",
    lyrics?.songId ?? "",
    lyrics?.currentLine?.id ?? "",
    lyrics?.nextLine?.id ?? "",
    playing,
  ].join("|");
}

export type ReconnectingSocketOptions = {
  url: string;
  /** Called every time a fresh connection opens (send a full snapshot here). */
  onOpen: () => void;
  /** Called with the text of each message Kotonoha sends back (e.g. config frames). */
  onMessage?: (data: string) => void;
  /** Optional logger for diagnostics. */
  log?: (message: string, error?: unknown) => void;
  /** Backoff bounds in milliseconds. */
  minBackoffMs?: number;
  /** How long one connection attempt may sit in CONNECTING before it is retried. */
  openTimeoutMs?: number;
  /** How many bytes may sit unsent before frames are dropped rather than queued. */
  maxBufferedBytes?: number;
  maxBackoffMs?: number;
  /** Injectable for tests; defaults to the global WebSocket. */
  socketFactory?: (url: string) => WebSocket;
  /** Injectable timers for tests. */
  setTimeoutFn?: (handler: () => void, timeout: number) => number;
  clearTimeoutFn?: (handle: number) => void;
};

/**
 * Minimal WebSocket client that keeps trying to (re)connect with exponential
 * backoff. The Cider plugin uses it to stream lyric frames to Kotonoha; when
 * Kotonoha is not running yet, it simply retries quietly until it is.
 */
export class ReconnectingLyricsSocket {
  private ws: WebSocket | null = null;
  private backoff: number;
  private reconnectTimer: number | null = null;
  private closedByUser = false;

  private readonly url: string;
  private readonly onOpen: () => void;
  private readonly onMessage: (data: string) => void;
  private readonly log: (message: string, error?: unknown) => void;
  private readonly minBackoffMs: number;
  private readonly openTimeoutMs: number;
  private readonly maxBufferedBytes: number;
  private openTimer: number | null = null;
  /** Rises per attempt so a stale callback from an abandoned socket is ignored. */
  private generation = 0;
  private readonly maxBackoffMs: number;
  private readonly socketFactory: (url: string) => WebSocket;
  private readonly setTimeoutFn: (handler: () => void, timeout: number) => number;
  private readonly clearTimeoutFn: (handle: number) => void;

  constructor(options: ReconnectingSocketOptions) {
    this.url = options.url;
    this.onOpen = options.onOpen;
    this.onMessage = options.onMessage ?? (() => {});
    this.log = options.log ?? (() => {});
    this.minBackoffMs = options.minBackoffMs ?? 500;
    this.openTimeoutMs = options.openTimeoutMs ?? 10_000;
    this.maxBufferedBytes = options.maxBufferedBytes ?? 1 << 20;
    this.maxBackoffMs = options.maxBackoffMs ?? 5000;
    this.socketFactory = options.socketFactory ?? ((url) => new WebSocket(url));
    this.setTimeoutFn = options.setTimeoutFn ?? ((h, t) => window.setTimeout(h, t));
    this.clearTimeoutFn = options.clearTimeoutFn ?? ((h) => window.clearTimeout(h));
    this.backoff = this.minBackoffMs;
  }

  get isOpen(): boolean {
    return this.ws !== null && this.ws.readyState === OPEN_READY_STATE;
  }

  connect(): void {
    this.closedByUser = false;
    this.openSocket();
  }

  private openSocket(): void {
    if (this.reconnectTimer !== null) {
      this.clearTimeoutFn(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    let socket: WebSocket;
    try {
      socket = this.socketFactory(this.url);
    } catch (error) {
      this.log("failed to construct socket", error);
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;
    const attempt = ++this.generation;

    // A constructor that returns does not mean a connection: a socket can sit in
    // CONNECTING for as long as the peer leaves it there, and neither onclose nor
    // onerror ever fires. Reconnects were scheduled only from those two, so such
    // an attempt was the last one the plugin ever made.
    this.clearOpenTimer();
    this.openTimer = this.setTimeoutFn(() => {
      this.openTimer = null;
      if (attempt !== this.generation || this.closedByUser) {
        return;
      }
      this.log("connection attempt timed out");
      try {
        socket.close();
      } catch (error) {
        this.log("closing a timed-out attempt failed", error);
      }
      this.scheduleReconnect();
    }, this.openTimeoutMs);

    socket.onopen = () => {
      if (attempt !== this.generation) {
        return;
      }
      this.clearOpenTimer();
      this.backoff = this.minBackoffMs;
      this.log("connected");
      this.onOpen();
    };
    socket.onmessage = (event: MessageEvent) => {
      if (attempt === this.generation && typeof event.data === "string") {
        this.onMessage(event.data);
      }
    };
    socket.onclose = () => {
      if (attempt !== this.generation) {
        return;
      }
      this.clearOpenTimer();
      this.log("disconnected");
      this.scheduleReconnect();
    };
    socket.onerror = (event) => {
      this.log("socket error", event);
      // onclose follows onerror; reconnect is scheduled there.
    };
  }

  private scheduleReconnect(): void {
    this.ws = null;
    if (this.closedByUser || this.reconnectTimer !== null) {
      return;
    }
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, this.maxBackoffMs);
    this.reconnectTimer = this.setTimeoutFn(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delay);
  }

  private clearOpenTimer(): void {
    if (this.openTimer !== null) {
      this.clearTimeoutFn(this.openTimer);
      this.openTimer = null;
    }
  }

  /** Whether the socket has room for another frame.
   *
   * A receiver that stops reading does not close the connection: the browser keeps
   * accepting frames into its own buffer, so send() reporting success meant only
   * that nothing threw. Ticks kept arriving and the buffer kept growing.
   */
  get writable(): boolean {
    return this.isOpen && this.ws !== null && this.ws.bufferedAmount <= this.maxBufferedBytes;
  }

  /** Queue a text frame if the socket is open and not already backed up.
   *
   * Named for what it does: the browser owns delivery from here, so a true return
   * means the frame was handed over, not that the receiver has seen it.
   */
  send(data: string): boolean {
    if (!this.isOpen || this.ws === null) {
      return false;
    }
    if (this.ws.bufferedAmount > this.maxBufferedBytes) {
      this.log(`dropping a frame: ${this.ws.bufferedAmount} bytes already queued`);
      return false;
    }
    try {
      this.ws.send(data);
      return true;
    } catch (error) {
      this.log("send failed", error);
      return false;
    }
  }

  close(): void {
    this.closedByUser = true;
    this.generation += 1;
    this.clearOpenTimer();
    if (this.reconnectTimer !== null) {
      this.clearTimeoutFn(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws !== null) {
      try {
        this.ws.close();
      } catch {
        // ignore
      }
      this.ws = null;
    }
  }
}
