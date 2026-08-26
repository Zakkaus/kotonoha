export type ProbeConfig = {
  /** Generic Kotonoha adapter endpoint, e.g. ws://127.0.0.1:28745/kotonoha/adapter */
  endpoint: string;
  /** How often to sample Cider state for change detection. */
  pollMs: number;
  /** Floor interval for repeated snapshot messages when nothing changes. */
  heartbeatMs: number;
  /** Interval for lightweight clock messages that calibrate the receiver clock. */
  tickMs: number;
  consoleLog: boolean;
};

export type FrameReason = "open" | "change" | "heartbeat" | "manual";

export type TimedLyricWord = {
  start: number | null;
  end: number | null;
  text: string;
};

export type TimedLyricLine = {
  index: number;
  id: string;
  start: number;
  end: number;
  text: string;
  translation: string;
  words: TimedLyricWord[];
};

export type LyricsDocumentPayload = {
  /** Stable final lyric provider id, independent of the Cider transport. */
  source: string;
  sourceName: string | null;
  songId: string | null;
  timing: string | null;
  language: string | null;
  title: string | null;
  artist: string | null;
  album: string | null;
  durationS: number | null;
  lines: TimedLyricLine[];
};

export type NowPlayingItem = {
  title: string | null;
  artistName: string | null;
  albumName: string | null;
};

export type PlaybackTrackPayload = {
  stableId: string | null;
  title: string;
  rawTitle: string;
  artist: string;
  album: string;
  url: string | null;
  durationS: number | null;
};

export type PlaybackProbe = {
  playerId: string;
  status: "Playing" | "Paused" | "Stopped";
  positionS: number | null;
  durationS: number | null;
  track: PlaybackTrackPayload | null;
};

export type AdapterSnapshot = {
  protocol: "kotonoha.adapter";
  version: 1;
  type: "snapshot";
  adapter: string;
  sequence: number;
  capturedAt: string;
  playback: PlaybackProbe;
  lyrics: LyricsDocumentPayload | null;
};

export type AdapterClock = {
  protocol: "kotonoha.adapter";
  version: 1;
  type: "clock";
  adapter: string;
  sequence: number;
  capturedAt: string;
  trackRef: string | null;
  positionS: number | null;
  status: PlaybackProbe["status"];
};

export type ProbePayload = AdapterSnapshot;
