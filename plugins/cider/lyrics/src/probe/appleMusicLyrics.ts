import { parseAppleMusicTtml } from "./ttml";
import type { LyricsDocumentPayload, TimedLyricLine } from "./types";

type CiderGlobals = {
  CiderApp?: any;
  MusicKit?: any;
};

type LyricsCacheEntry = {
  songId: string;
  timing: string | null;
  language: string | null;
  durationS: number | null;
  lines: TimedLyricLine[];
};

let currentLyrics: LyricsCacheEntry | null = null;

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function currentNowPlayingItem(globals: CiderGlobals): any {
  return globals.MusicKit?.getInstance?.()?.nowPlayingItem ?? null;
}

export function currentSongId(globals: CiderGlobals): string | null {
  return (
    globals.CiderApp?.musicKitStore?.player?.nowPlayingId ??
    globals.CiderApp?.musicKitStore?.player?.nowPlayingItem?._songId ??
    globals.CiderApp?.musicKitStore?.player?.nowPlayingItem?.id ??
    currentNowPlayingItem(globals)?._songId ??
    currentNowPlayingItem(globals)?.id ??
    null
  );
}

function currentDurationSeconds(globals: CiderGlobals): number | null {
  const item = currentNowPlayingItem(globals);
  const milliseconds = numberOrNull(item?.attributes?.durationInMillis);
  return milliseconds === null ? null : milliseconds / 1000;
}

function documentFromEntry(entry: LyricsCacheEntry): LyricsDocumentPayload {
  return {
    source: "apple-music",
    sourceName: "Apple Music",
    songId: entry.songId,
    timing: entry.timing,
    language: entry.language,
    title: null,
    artist: null,
    album: null,
    durationS: entry.durationS,
    lines: entry.lines,
  };
}

async function fetchLyrics(globals: CiderGlobals, songId: string): Promise<LyricsCacheEntry> {
  const response = await globals.CiderApp?.mkfetch?.(
    `/v1/catalog/$MUSIC_STOREFRONT/songs/${songId}/syllable-lyrics`,
  );
  const ttml = response?.data?.data?.[0]?.attributes?.ttml;
  if (typeof ttml !== "string" || ttml.trim().length === 0) {
    throw new Error("No Apple Music TTML returned");
  }

  const durationS = currentDurationSeconds(globals);
  const parsed = parseAppleMusicTtml(ttml, { durationSeconds: durationS });
  return {
    songId,
    timing: parsed.timing,
    language: parsed.language,
    durationS,
    lines: parsed.lines,
  };
}

/** How long a song that produced no lyrics is left alone before trying again. */
const RETRY_AFTER_MS = 60_000;
/** Songs whose lookup failed, and when. Bounded so it cannot grow with a queue. */
const failedSongs = new Map<string, number>();
const MAX_REMEMBERED_FAILURES = 64;

function rememberFailure(songId: string): void {
  if (failedSongs.size >= MAX_REMEMBERED_FAILURES) {
    const oldest = failedSongs.keys().next();
    if (!oldest.done) {
      failedSongs.delete(oldest.value);
    }
  }
  failedSongs.set(songId, Date.now());
}

export async function probeAppleMusicLyrics(globals: CiderGlobals): Promise<LyricsDocumentPayload | null> {
  const songId = currentSongId(globals);
  if (!songId) {
    return null;
  }

  if (currentLyrics?.songId === songId) {
    return documentFromEntry(currentLyrics);
  }

  const failedAt = failedSongs.get(songId);
  if (failedAt !== undefined && Date.now() - failedAt < RETRY_AFTER_MS) {
    return null;
  }

  try {
    currentLyrics = await fetchLyrics(globals, songId);
    failedSongs.delete(songId);
    return documentFromEntry(currentLyrics);
  } catch {
    currentLyrics = null;
    rememberFailure(songId);
    return null;
  }
}
