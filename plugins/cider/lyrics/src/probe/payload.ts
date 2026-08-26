import { probeAppleMusicLyrics } from "./appleMusicLyrics";
import { probePlayback } from "./playback";
import type { AdapterSnapshot } from "./types";

export async function createProbePayload(options: {
  globals: any;
  version: string;
  sequence: number;
}): Promise<AdapterSnapshot> {
  return {
    protocol: "kotonoha.adapter",
    version: 1,
    type: "snapshot",
    adapter: "cider",
    sequence: options.sequence,
    capturedAt: new Date().toISOString(),
    playback: probePlayback(options.globals),
    lyrics: await probeAppleMusicLyrics(options.globals),
  };
}
