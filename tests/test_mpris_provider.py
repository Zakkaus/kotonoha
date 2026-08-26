import asyncio

from kotonoha.display.coordinator import DisplayCoordinator
from kotonoha.display.models import DisplayState
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind
from kotonoha.lyrics.ownership import SourceOwnershipCoordinator
from kotonoha.lyrics.sources import LyricsSourceResult
from kotonoha.lyrics.workflow import ResolverLookup, ResolverPort
from kotonoha.playback.coordinator import PlaybackCoordinator, PlaybackSample
from kotonoha.playback.models import MprisPlayerPort, PlaybackObservation, PlaybackStatus, TrackIdentity
from kotonoha.providers.mpris_lyrics import MprisLyricsCoordinator
from kotonoha.providers.mpris_track import TrackCommit, TrackInfo, parse_metadata
from kotonoha.state import LyricsState

VALID_METADATA: dict[str, object] = {
    "xesam:title": "Song",
    "xesam:artist": ["Artist"],
    "xesam:album": "Album",
    "mpris:length": 180_000_000,
    "mpris:trackid": "/track/1",
}


class FakePlayer:
    def __init__(self, metadata: dict[str, object], *, position: int = 0) -> None:
        self.metadata = metadata
        self.position = position

    async def get_playback_status(self) -> str:
        return "Playing"

    async def get_metadata(self) -> dict[str, object]:
        return self.metadata

    async def get_position(self) -> int:
        return self.position


class FakeSession:
    def __init__(self, player: FakePlayer | None) -> None:
        self.player_value = player
        self.connected = True
        self.closed = False
        self.subscriptions: list[str] = []

    async def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True
        self.connected = False

    async def player_names(self) -> list[str]:
        return ["org.mpris.MediaPlayer2.test"] if self.player_value is not None else []

    async def player(self, _name: str) -> MprisPlayerPort | None:
        return self.player_value

    async def status(self, player: MprisPlayerPort) -> str:
        return await player.get_playback_status()

    async def track(self, player: MprisPlayerPort) -> TrackInfo | None:
        return parse_metadata(await player.get_metadata())

    async def position(self, player: MprisPlayerPort) -> float | None:
        return float(await player.get_position()) / 1_000_000.0

    async def identity(self) -> str:
        return "Test Player"

    async def describe(self, _name: str) -> tuple[str, str, TrackInfo]:
        if self.player_value is None:
            raise LookupError
        return "Test Player", "Playing", parse_metadata(await self.player_value.get_metadata())

    async def subscribe(self, name: str, _callback) -> None:
        self.subscriptions.append(name)


class RecordingResolver:
    def __init__(self, result: LyricsSourceResult | None = None) -> None:
        self.tracks = []
        self.result = result
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def resolve(self, _session, track, _sources, /):
        self.tracks.append(track)
        self.started.set()
        if self.block:
            await self.release.wait()
        return self.result

    async def resolve_hint(self, _session, _track, _sources, _hint, /):
        return None

    async def resolve_with_diagnostics(self, session, track, sources, /):
        return ResolverLookup(await self.resolve(session, track, sources))

    @property
    def live_source_id(self) -> str:
        return "cider"

    def reset_memory(self) -> None:
        return None

    def set_cache_enabled(self, _enabled: bool) -> None:
        return None

    def set_prefer_best(self, _enabled: bool) -> None:
        return None

    def set_fuzzy(self, _enabled: bool) -> None:
        return None

    async def clear_cache(self) -> None:
        return None

    async def cancel_inflight(self) -> None:
        return None

    async def close(self) -> None:
        return None


def track_commit(generation: int, title: str = "Song", artist: str = "Artist") -> TrackCommit:
    return TrackCommit(
        generation=generation,
        player_name="org.mpris.MediaPlayer2.test",
        info=TrackInfo(title, artist, "Album", 180.0, f"/{generation}"),
    )


def lyric_result(source_id: str = "netease") -> LyricsSourceResult:
    lines = (LyricLine(0, "L0", 0.0, 5.0, "first", ""), LyricLine(1, "L1", 5.0, 10.0, "second", ""))
    return LyricsSourceResult(
        source_id,
        document=LyricsDocument(
            source_id,
            source_name="Resolved Provider",
            song_id="provider-song-1",
            timing=TimingKind.LINE,
            language="en",
            title="Song",
            artist="Artist",
            duration_s=180.0,
            lines=lines,
        ),
    )


def cider_facts():
    line = LyricLine(0, "L0", 0.0, 5.0, "Song", "")
    document = LyricsDocument("apple-music", timing=TimingKind.LINE, title="Song", artist="Artist", lines=(line,))
    track = TrackIdentity("cider", "cider", stable_id="song-1", title="Song", artist="Artist")
    observation = PlaybackObservation("cider", "cider", track, PlaybackStatus.PLAYING, 1.0, 180.0, 1.0)
    return observation, document


async def test_playback_coordinator_owns_sampling_and_commits_stable_tracks():
    player = FakePlayer(VALID_METADATA, position=3_000_000)
    session = FakeSession(player)
    commits = []
    samples: list[PlaybackSample] = []
    coordinator = PlaybackCoordinator(
        session=session,
        on_sample=samples.append,
        on_commit=commits.append,
    )

    await coordinator.poll_once(now=0.0)
    await coordinator.poll_once(now=0.5)

    assert session.subscriptions == ["org.mpris.MediaPlayer2.test"]
    assert len(commits) == 1
    assert coordinator.current_commit == commits[0]
    assert samples[-1].observation.adapter_id == "mpris"
    assert samples[-1].observation.status is PlaybackStatus.PLAYING
    assert samples[-1].observation.position_s == 3.0


async def test_playback_coordinator_closes_its_session_and_poll_task():
    session = FakeSession(None)
    coordinator = PlaybackCoordinator(session=session, poll_interval=0.01)

    await coordinator.start()
    await asyncio.sleep(0)
    await coordinator.stop()
    await coordinator.stop()

    assert session.closed is True


async def test_playback_coordinator_reports_no_player():
    calls: list[float] = []
    coordinator = PlaybackCoordinator(session=FakeSession(None), on_no_player=calls.append)

    await coordinator.poll_once(now=4.0)

    assert calls == [4.0]


def lyrics_coordinator(
    display: DisplayCoordinator,
    *,
    resolver: ResolverPort,
    ownership: SourceOwnershipCoordinator,
) -> MprisLyricsCoordinator:
    """Build the lyric workflow through its public coordinator contract."""
    return MprisLyricsCoordinator(display, resolver=resolver, ownership=ownership)


async def test_new_generation_cancels_old_resolution():
    resolver = RecordingResolver()
    resolver.block = True
    coordinator = lyrics_coordinator(
        DisplayCoordinator(LyricsState()),
        resolver=resolver,
        ownership=SourceOwnershipCoordinator(),
    )
    coordinator.on_playback_commit(track_commit(1, "A", "Artist A"))
    await resolver.started.wait()

    coordinator.on_playback_commit(track_commit(2, "B", "Artist B"))
    assert coordinator.load_task is not None
    resolver.release.set()
    await coordinator.load_task

    assert [track.title for track in resolver.tracks] == ["A", "B"]
    assert coordinator.current_commit is not None
    assert coordinator.current_commit.info.title == "B"


async def test_external_result_is_projected_to_the_canonical_frame():
    state = LyricsState()
    coordinator = lyrics_coordinator(
        DisplayCoordinator(state),
        resolver=RecordingResolver(lyric_result("lrclib")),
        ownership=SourceOwnershipCoordinator(),
    )
    coordinator.on_playback_commit(track_commit(1))
    assert coordinator.load_task is not None
    await coordinator.load_task

    observation = PlaybackObservation(
        "mpris",
        "org.mpris.MediaPlayer2.test",
        TrackIdentity("mpris", "test", title="Song", artist="Artist", duration_s=180.0),
        PlaybackStatus.PLAYING,
        2.0,
        180.0,
        1.0,
    )
    coordinator.on_playback_sample(PlaybackSample(observation, track_commit(1).info, False, None))

    assert state.frame.state is DisplayState.LYRICS_AVAILABLE
    assert state.frame.document is not None
    assert state.frame.document.source_id == "lrclib"
    assert state.frame.document.source_name == "Resolved Provider"
    assert state.frame.document.song_id == "provider-song-1"
    assert state.frame.document.language == "en"
    assert state.frame.current is not None


async def test_cider_frame_can_take_over_after_a_late_external_miss():
    resolver = RecordingResolver()
    gate = SourceOwnershipCoordinator()
    state = LyricsState()
    coordinator = lyrics_coordinator(DisplayCoordinator(state), resolver=resolver, ownership=gate)
    coordinator.on_playback_commit(track_commit(1))
    await resolver.started.wait()

    observation, document = cider_facts()
    gate.observe(10, observation, document)
    resolver.release.set()
    assert coordinator.load_task is not None
    await coordinator.load_task

    assert coordinator.content_owner == "live"
    assert gate.accepts(10) is True
    assert state.frame.document is not None


async def test_matching_cider_clock_can_drive_external_timeline():
    state = LyricsState()
    gate = SourceOwnershipCoordinator()
    observation, document = cider_facts()
    gate.observe(10, observation, document)
    gate.observe_clock(10, observation.track.track_ref, 7.5, True)
    resolver = RecordingResolver(lyric_result())
    coordinator = lyrics_coordinator(DisplayCoordinator(state), resolver=resolver, ownership=gate)
    coordinator.on_playback_commit(track_commit(1))
    assert coordinator.load_task is not None
    await coordinator.load_task

    info = track_commit(1).info
    observation = PlaybackObservation(
        "mpris",
        "org.mpris.MediaPlayer2.test",
        TrackIdentity("mpris", "test", title="Song", artist="Artist", duration_s=180.0),
        PlaybackStatus.PLAYING,
        999.0,
        180.0,
        1.0,
    )
    coordinator.on_playback_sample(PlaybackSample(observation, info, False, None))

    assert state.frame.current_time == 7.5


async def test_non_song_is_not_sent_to_the_resolver():
    resolver = RecordingResolver()
    coordinator = lyrics_coordinator(
        DisplayCoordinator(LyricsState()),
        resolver=resolver,
        ownership=SourceOwnershipCoordinator(),
    )
    commit = track_commit(1, "Study with Miku - part4 -")
    commit = TrackCommit(commit.generation, commit.player_name, replace_length(commit.info, 7201.0))

    coordinator.on_playback_commit(commit)
    assert coordinator.load_task is not None
    await coordinator.load_task

    assert resolver.tracks == []
    assert coordinator.content_owner == "none"


def replace_length(info: TrackInfo, length_s: float) -> TrackInfo:
    return TrackInfo(info.title, info.artist, info.album, length_s, info.track_id, info.reported_title, info.url)
