import { describe, expect, it, vi } from "vitest";

import { ReconnectingLyricsSocket, frameSignature } from "../probe/transport";

const baseFrame = {
  lyrics: {
    source: "apple-music",
    songId: "song-1",
    lines: [{ id: "L1" }, { id: "L2" }],
  },
  playback: { status: "Playing", track: { stableId: "song-1" } },
} as any;

describe("frameSignature", () => {
  it("is stable for equivalent frames", () => {
    expect(frameSignature(baseFrame)).toBe(frameSignature({ ...baseFrame }));
  });

  it("changes when the lyric document changes", () => {
    const moved = { ...baseFrame, lyrics: { ...baseFrame.lyrics, lines: [{ id: "L1" }, { id: "L3" }] } };
    expect(frameSignature(moved)).not.toBe(frameSignature(baseFrame));
  });

  it("changes when play/pause toggles", () => {
    const paused = { ...baseFrame, playback: { ...baseFrame.playback, status: "Paused" } };
    expect(frameSignature(paused)).not.toBe(frameSignature(baseFrame));
  });

  it("tolerates missing sections", () => {
    expect(frameSignature({ lyrics: undefined, playback: undefined } as any)).toBe("|||");
  });
});

// A minimal fake matching the slice of WebSocket the socket touches.
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readyState = 1; // OPEN
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  bufferedAmount = 0;
  close() {
    this.closed = true;
  }
}

const OPEN_TIMEOUT_MS = 10_000;

function makeSocket(overrides: Partial<ConstructorParameters<typeof ReconnectingLyricsSocket>[0]> = {}) {
  FakeWebSocket.instances = [];
  const timers: Array<{ handler: () => void; delay: number }> = [];
  const onOpen = vi.fn();
  const socket = new ReconnectingLyricsSocket({
    url: "ws://test/endpoint",
    onOpen,
    minBackoffMs: 500,
    maxBackoffMs: 5000,
    openTimeoutMs: OPEN_TIMEOUT_MS,
    socketFactory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
    setTimeoutFn: (handler, delay) => {
      timers.push({ handler, delay });
      return timers.length - 1;
    },
    clearTimeoutFn: () => {},
    ...overrides,
  });
  // Two kinds of timer are scheduled now — the reconnect backoff and the deadline
  // on one connection attempt — so they are told apart by intent rather than by the
  // order they happen to be created in.
  const reconnects = () => timers.filter((timer) => timer.delay !== OPEN_TIMEOUT_MS);
  const openDeadlines = () => timers.filter((timer) => timer.delay === OPEN_TIMEOUT_MS);
  return {
    socket,
    timers,
    reconnects,
    openDeadlines,
    onOpen,
    latest: () => FakeWebSocket.instances.at(-1)!,
  };
}

describe("ReconnectingLyricsSocket", () => {
  it("calls onOpen and reports open after connect", () => {
    const { socket, onOpen, latest } = makeSocket();
    socket.connect();
    latest().onopen?.();
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(socket.isOpen).toBe(true);
  });

  it("queues a reconnect with exponential backoff on close", () => {
    const { socket, reconnects, latest } = makeSocket();
    socket.connect();
    latest().onopen?.();

    latest().onclose?.();
    expect(reconnects()).toHaveLength(1);
    expect(reconnects()[0].delay).toBe(500);

    // Fire the scheduled reconnect, then close again -> backoff doubles.
    reconnects()[0].handler();
    latest().onclose?.();
    expect(reconnects()[1].delay).toBe(1000);
  });

  it("resets backoff after a successful reopen", () => {
    const { socket, reconnects, latest } = makeSocket();
    socket.connect();
    latest().onclose?.();
    expect(reconnects()[0].delay).toBe(500);
    reconnects()[0].handler();
    latest().onclose?.();
    expect(reconnects()[1].delay).toBe(1000);

    reconnects()[1].handler();
    latest().onopen?.(); // success resets backoff
    latest().onclose?.();
    expect(reconnects()[2].delay).toBe(500);
  });

  it("send returns false when not open and true when open", () => {
    const { socket, latest } = makeSocket();
    expect(socket.send("x")).toBe(false); // not connected yet
    socket.connect();
    latest().onopen?.();
    expect(socket.send("hello")).toBe(true);
    expect(latest().sent).toEqual(["hello"]);
  });

  it("stops reconnecting after close()", () => {
    const { socket, reconnects, latest } = makeSocket();
    socket.connect();
    const ws = latest();
    socket.close();
    ws.onclose?.();
    expect(reconnects()).toHaveLength(0);
    expect(ws.closed).toBe(true);
  });

  it("retries an attempt that never leaves CONNECTING", () => {
    // A constructor that returns is not a connection: a socket can sit in
    // CONNECTING for as long as the peer leaves it there, and neither onclose nor
    // onerror ever fires. Reconnects were scheduled only from those two, so such
    // an attempt was the last one the plugin ever made.
    const { socket, reconnects, openDeadlines, latest } = makeSocket();
    socket.connect();
    const stuck = latest();

    expect(openDeadlines()).toHaveLength(1);
    expect(reconnects()).toHaveLength(0);

    openDeadlines()[0].handler();

    expect(stuck.closed).toBe(true);
    expect(reconnects()).toHaveLength(1);
  });

  it("drops a frame rather than queueing it behind a stalled receiver", () => {
    // A receiver that stops reading does not close the connection: the browser
    // keeps accepting frames into its own buffer, so send() reporting success
    // meant only that nothing threw while the buffer grew.
    const { socket, latest } = makeSocket({ maxBufferedBytes: 100 } as never);
    socket.connect();
    const ws = latest();
    ws.onopen?.();

    expect(socket.send("small")).toBe(true);
    (ws as unknown as { bufferedAmount: number }).bufferedAmount = 5000;

    expect(socket.writable).toBe(false);
    expect(socket.send("another")).toBe(false);
    expect(ws.sent).toHaveLength(1);
  });
});
