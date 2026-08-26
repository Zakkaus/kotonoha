import { describe, expect, it } from "vitest";

import { probePlayback } from "../probe/playback";

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
      playerId: "cider",
      status: "Playing",
      positionS: 42,
      durationS: 180,
      track: {
        stableId: null,
        title: "Song",
        rawTitle: "Song",
        artist: "",
        album: "",
        url: null,
        durationS: 180,
      },
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
      playerId: "cider",
      status: "Stopped",
      positionS: 8,
      track: { title: "Fallback" },
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
      playerId: "cider",
      status: "Playing",
      positionS: 41,
      durationS: 180,
      track: { title: "Current Song" },
    });
  });

  it("uses MusicKit for the playback clock when Cider exposes no audio element", () => {
    const globals = {
      CiderApp: {
        musicKitStore: {
          player: {
            isPlaying: true,
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

    expect(probePlayback(globals)).toMatchObject({
      positionS: 42.5,
      status: "Playing",
    });
  });

  it("survives an item Cider made cyclic", () => {
    // The raw object was forwarded whole and the frame is JSON.stringify'd, so a
    // cycle threw and no frame was delivered at all — with logging off, silently.
    const cyclic: Record<string, unknown> = { attributes: { name: "Looped", artistName: "A" } };
    cyclic.self = cyclic;

    const probe = probePlayback({ MusicKit: { getInstance: () => ({ nowPlayingItem: cyclic }) } });

    expect(probe.track).toMatchObject({ title: "Looped", artist: "A" });
    expect(() => JSON.stringify(probe)).not.toThrow();
  });
});
