import { describe, expect, it } from "vitest";

import { probePlayback, probePlaybackTime } from "../probe/playback";

describe("probePlayback", () => {
  it("reads the PluginKit apple music store when present", () => {
    const globals = {
      __PLUGINSYS__: {
        Stores: {
          appleMusicStore: {
            nowPlayingItem: { title: "Song" },
            isPlaying: true,
            currentPlaybackTime: 42,
            audioElement: {
              currentTime: 42.5,
              duration: 180,
            },
          },
        },
      },
    };

    expect(probePlayback(globals)).toEqual({
      // Projected, not forwarded: only the three fields the receiver reads.
      nowPlayingItem: { title: "Song", artistName: null, albumName: null },
      isPlaying: true,
      currentPlaybackTime: 42,
      audioCurrentTime: 42.5,
      audioDuration: 180,
    });
  });

  it("falls back to CiderApp musicKitStore", () => {
    const globals = {
      CiderApp: {
        musicKitStore: {
          nowPlayingItem: { title: "Fallback" },
          playbackTime: 8,
        },
      },
    };

    expect(probePlayback(globals)).toMatchObject({
      nowPlayingItem: { title: "Fallback" },
      currentPlaybackTime: 8,
    });
  });

  it("reads the current Cider nested player layout", () => {
    const nowPlayingItem = { attributes: { name: "Current Song" } };
    const globals = {
      CiderApp: {
        musicKitStore: {
          player: {
            nowPlayingItem,
            isPlaying: true,
            currentPlaybackTime: 41,
            currentPlaybackDuration: 180,
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          nowPlayingItem,
          isPlaying: true,
          currentPlaybackTime: 42.5,
          currentPlaybackDuration: 180,
        }),
      },
    };

    expect(probePlayback(globals)).toMatchObject({
      // The nested attributes shape is read and flattened to what the receiver takes.
      nowPlayingItem: { title: "Current Song", artistName: null, albumName: null },
      isPlaying: true,
      currentPlaybackTime: 41,
      currentPlaybackDuration: 180,
    });
  });

  it("uses MusicKit for a high-frequency tick when Cider exposes no audio element", () => {
    const globals = {
      CiderApp: {
        musicKitStore: {
          player: {
            isPlaying: true,
            currentPlaybackTime: 41,
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          isPlaying: true,
          currentPlaybackTime: 42.5,
        }),
      },
    };

    expect(probePlaybackTime(globals)).toEqual({
      currentTime: 42.5,
      isPlaying: true,
    });
  });

  it("survives an item Cider made cyclic", () => {
    // The raw object was forwarded whole and the frame is JSON.stringify'd, so a
    // cycle threw and no frame was delivered at all — with logging off, silently.
    const cyclic: Record<string, unknown> = { attributes: { name: "Looped", artistName: "A" } };
    cyclic.self = cyclic;

    const probe = probePlayback({ MusicKit: { getInstance: () => ({ nowPlayingItem: cyclic }) } });

    expect(probe.nowPlayingItem).toEqual({ title: "Looped", artistName: "A", albumName: null });
    expect(() => JSON.stringify(probe)).not.toThrow();
  });
});
