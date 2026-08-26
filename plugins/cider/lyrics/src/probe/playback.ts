import { currentSongId } from "./appleMusicLyrics";
import type { NowPlayingItem, PlaybackProbe, PlaybackTrackPayload } from "./types";

type CiderGlobals = {
  /** Keeps the browser Window object assignable at the third-party global boundary. */
  window?: Window;
  CiderApp?: any;
  __PLUGINSYS__?: any;
  MusicKit?: any;
};

function numberOrUndefined(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function booleanOrUndefined(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function hasPlaybackState(value: any): boolean {
  return Boolean(
    value && (
      value.nowPlayingItem != null ||
      numberOrUndefined(value.currentPlaybackTime ?? value.playbackTime) !== undefined ||
      typeof value.isPlaying === "boolean" ||
      value.audioElement
    ),
  );
}

function playbackPlayer(globals: CiderGlobals): any {
  const pluginStore = globals.__PLUGINSYS__?.Stores?.appleMusicStore;
  if (hasPlaybackState(pluginStore)) {
    return pluginStore;
  }
  const musicKitStore = globals.CiderApp?.musicKitStore;
  if (hasPlaybackState(musicKitStore?.player)) {
    return musicKitStore.player;
  }
  if (hasPlaybackState(musicKitStore)) {
    return musicKitStore;
  }
  return globals.CiderApp?.store;
}

function musicKit(globals: CiderGlobals): any {
  return globals.MusicKit?.getInstance?.();
}

function audioElement(globals: CiderGlobals, player: any): any {
  return player?.audioElement ?? globals.CiderApp?.musicKitStore?.audioElement;
}

/** Read the small, stable metadata subset used by the adapter wire contract. */
function projectNowPlaying(item: unknown): NowPlayingItem | null {
  if (item === null || typeof item !== "object") {
    return null;
  }
  const record = item as Record<string, unknown>;
  const attributes =
    typeof record.attributes === "object" && record.attributes !== null
      ? (record.attributes as Record<string, unknown>)
      : {};
  const pick = (...names: string[]): string | null => {
    for (const name of names) {
      const value = attributes[name] ?? record[name];
      if (typeof value === "string" && value.length > 0) {
        return value;
      }
    }
    return null;
  };
  return {
    title: pick("name", "title"),
    artistName: pick("artistName"),
    albumName: pick("albumName"),
  };
}

function playbackDuration(player: any, instance: any, audio: any): number | null {
  return (
    numberOrUndefined(player?.currentPlaybackDuration ?? player?.playbackDuration) ??
    numberOrUndefined(instance?.currentPlaybackDuration) ??
    numberOrUndefined(audio?.duration) ??
    null
  );
}

function playbackPosition(player: any, instance: any, audio: any): number | null {
  return (
    numberOrUndefined(player?.currentPlaybackTime ?? player?.playbackTime) ??
    numberOrUndefined(instance?.currentPlaybackTime) ??
    numberOrUndefined(audio?.currentTime) ??
    null
  );
}

export function probePlayback(globals: CiderGlobals): PlaybackProbe {
  const player = playbackPlayer(globals);
  const instance = musicKit(globals);
  const audio = audioElement(globals, player);
  const item = projectNowPlaying(player?.nowPlayingItem ?? instance?.nowPlayingItem ?? null);
  const stableId = currentSongId(globals);
  const positionS = playbackPosition(player, instance, audio);
  const durationS = playbackDuration(player, instance, audio);
  const isPlaying =
    booleanOrUndefined(player?.isPlaying) ??
    booleanOrUndefined(instance?.isPlaying) ??
    (typeof audio?.paused === "boolean" ? !audio.paused : undefined);

  let track: PlaybackTrackPayload | null = null;
  if (item !== null || stableId !== null) {
    track = {
      stableId,
      title: item?.title ?? "",
      rawTitle: item?.title ?? "",
      artist: item?.artistName ?? "",
      album: item?.albumName ?? "",
      url: null,
      durationS,
    };
  }

  return {
    playerId: "cider",
    status: isPlaying === true ? "Playing" : isPlaying === false ? "Paused" : "Stopped",
    positionS,
    durationS,
    track,
  };
}
