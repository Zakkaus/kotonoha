import { describe, expect, it, vi } from "vitest";

import { probeAppleMusicLyrics } from "../probe/appleMusicLyrics";

const TTML = `
<tt xmlns="http://www.w3.org/ns/ttml"
    xmlns:itunes="http://music.apple.com/lyric-ttml-internal"
    xml:lang="en"
    itunes:timing="Line">
  <body>
    <div>
      <p xml:id="L1" begin="00:01.000" end="00:03.000">hello</p>
      <p xml:id="L2" begin="00:03.000" end="00:05.000">world</p>
    </div>
  </body>
</tt>`;

describe("probeAppleMusicLyrics", () => {
  it("fetches and parses current Apple Music lyrics without using DOM", async () => {
    const mkfetch = vi.fn().mockResolvedValue({
      data: {
        data: [
          {
            attributes: {
              ttml: TTML,
            },
          },
        ],
      },
    });

    const result = await probeAppleMusicLyrics({
      CiderApp: {
        mkfetch,
        musicKitStore: {
          player: {
            nowPlayingId: "song-1",
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          currentPlaybackTime: 3.5,
          nowPlayingItem: {
            id: "song-1",
            attributes: {
              durationInMillis: 6000,
            },
          },
        }),
      },
    });

    expect(mkfetch).toHaveBeenCalledWith("/v1/catalog/$MUSIC_STOREFRONT/songs/song-1/syllable-lyrics");
    expect(result).toMatchObject({
      source: "apple-music",
      sourceName: "Apple Music",
      songId: "song-1",
      timing: "Line",
      language: "en",
      durationS: 6,
      lines: [{ id: "L1", text: "hello" }, { id: "L2", text: "world" }],
    });
  });

  it("keeps a complete document for the current song without refetching", async () => {
    const mkfetch = vi.fn().mockResolvedValue({
      data: {
        data: [
          {
            attributes: {
              ttml: TTML,
            },
          },
        ],
      },
    });
    const globals = {
      CiderApp: {
        mkfetch,
        musicKitStore: {
          player: {
            nowPlayingId: "song-3",
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          currentPlaybackTime: 3.5,
          nowPlayingItem: {
            id: "song-3",
            attributes: {
              durationInMillis: 6000,
            },
          },
        }),
      },
    };

    await probeAppleMusicLyrics(globals);
    const result = await probeAppleMusicLyrics(globals);

    expect(mkfetch).toHaveBeenCalledTimes(1);
    expect(result?.lines.map((line) => line.text)).toEqual(["hello", "world"]);
  });

  it("returns no document when lyrics are unavailable", async () => {
    const result = await probeAppleMusicLyrics({
      CiderApp: {
        mkfetch: vi.fn().mockResolvedValue({ data: { data: [{}] } }),
        musicKitStore: {
          player: {
            nowPlayingId: "song-2",
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          currentPlaybackTime: 0,
          nowPlayingItem: {
            id: "song-2",
            attributes: {
              durationInMillis: 6000,
            },
          },
        }),
      },
    });

    expect(result).toBeNull();
  });

  it("keeps previous/next correct when an empty <p> is filtered out", async () => {
    const ttml = `
<tt xmlns="http://www.w3.org/ns/ttml"
    xmlns:itunes="http://music.apple.com/lyric-ttml-internal"
    xml:lang="en" itunes:timing="Line">
  <body>
    <div>
      <p xml:id="X" begin="00:00.500" end="00:01.000"></p>
      <p xml:id="L1" begin="00:01.000" end="00:03.000">one</p>
      <p xml:id="L2" begin="00:03.000" end="00:05.000">two</p>
      <p xml:id="L3" begin="00:05.000" end="00:07.000">three</p>
    </div>
  </body>
</tt>`;
    const result = await probeAppleMusicLyrics({
      CiderApp: {
        mkfetch: vi.fn().mockResolvedValue({ data: { data: [{ attributes: { ttml } }] } }),
        musicKitStore: { player: { nowPlayingId: "song-9" } },
      },
      MusicKit: {
        getInstance: () => ({
          currentPlaybackTime: 3.5,
          nowPlayingItem: { id: "song-9", attributes: { durationInMillis: 8000 } },
        }),
      },
    });

    // The empty <p id="X"> is dropped by the filter, and the canonical document
    // preserves the filtered order for the shared display projection.
    expect(result?.lines.map((line) => line.id)).toEqual(["L1", "L2", "L3"]);
  });

  it("does not ask again for a song that has no lyrics", async () => {
    // A miss is remembered, so repeated snapshots do not refetch the same song.
    const mkfetch = vi.fn().mockResolvedValue({ data: { data: [{}] } });
    const globals = {
      CiderApp: { mkfetch, musicKitStore: { player: { nowPlayingId: "song-quiet" } } },
      MusicKit: {
        getInstance: () => ({
          currentPlaybackTime: 0,
          nowPlayingItem: { id: "song-quiet", attributes: { durationInMillis: 6000 } },
        }),
      },
    };

    const first = await probeAppleMusicLyrics(globals);
    const calls = mkfetch.mock.calls.length;
    const second = await probeAppleMusicLyrics(globals);
    const third = await probeAppleMusicLyrics(globals);

    expect(first).toBeNull();
    expect(second).toBeNull();
    expect(third).toBeNull();
    expect(mkfetch.mock.calls.length).toBe(calls);
  });
});
