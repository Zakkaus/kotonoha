from pathlib import Path

import pytest

from kotonoha.lyrics.local import load_local_lyrics


def test_loads_utf8_sidecar(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("[00:01.00]你好", encoding="utf-8")

    lines = load_local_lyrics(audio)

    assert [line.text for line in lines] == ["你好"]


def test_loads_gb18030_sidecar(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_bytes("[00:01.00]你好".encode("gb18030"))

    lines = load_local_lyrics(audio)

    assert [line.text for line in lines] == ["你好"]


def test_missing_sidecar_is_a_miss(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()

    assert load_local_lyrics(audio) == []


def test_empty_sidecar_is_a_miss(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("", encoding="utf-8")

    assert load_local_lyrics(audio) == []


def test_untimed_sidecar_is_a_miss(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("[ar:Artist]\n[ti:Song]", encoding="utf-8")

    assert load_local_lyrics(audio) == []


def test_sidecar_symlink_outside_audio_directory_is_a_miss(tmp_path: Path):
    audio_directory = tmp_path / "audio"
    outside_directory = tmp_path / "outside"
    audio_directory.mkdir()
    outside_directory.mkdir()
    audio = audio_directory / "song.flac"
    audio.touch()
    outside = outside_directory / "lyrics.lrc"
    outside.write_text("[00:01.00]outside", encoding="utf-8")
    (audio_directory / "song.lrc").symlink_to(outside)

    assert load_local_lyrics(audio) == []


def test_sidecar_offset_tag_shifts_the_timings(tmp_path: Path):
    # The format's own wording: a "+" offset causes the lyrics to appear sooner,
    # so it comes off each timestamp. A sidecar written against a different rip is
    # commonly a second or two out without it.
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("[offset:+500]\n[00:02.00]line\n", encoding="utf-8")

    assert [line.start for line in load_local_lyrics(audio)] == [1.5]

    (tmp_path / "song.lrc").write_text("[offset:-500]\n[00:02.00]line\n", encoding="utf-8")
    assert [line.start for line in load_local_lyrics(audio)] == [2.5]

    # Junk far outside a plausible correction is not an instruction.
    (tmp_path / "song.lrc").write_text("[offset:999999]\n[00:02.00]line\n", encoding="utf-8")
    assert [line.start for line in load_local_lyrics(audio)] == [2.0]
def test_sidecar_wins_over_embedded_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mutagen = pytest.importorskip("mutagen")
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("[00:01.00]sidecar", encoding="utf-8")

    monkeypatch.setattr(
        mutagen,
        "File",
        lambda _: type("Audio", (), {"tags": {"LYRICS": ["[00:02.00]embedded"]}})(),
    )

    assert [line.text for line in load_local_lyrics(audio)] == ["sidecar"]


def test_loads_embedded_vorbis_lyrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mutagen = pytest.importorskip("mutagen")
    audio = tmp_path / "song.flac"
    audio.touch()
    tags = {"LYRICS": ["[00:01.00]embedded"]}
    monkeypatch.setattr(mutagen, "File", lambda _: type("Audio", (), {"tags": tags})())

    assert [line.text for line in load_local_lyrics(audio)] == ["embedded"]


def test_loads_embedded_unsynced_vorbis_lyrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mutagen = pytest.importorskip("mutagen")
    audio = tmp_path / "song.ogg"
    audio.touch()
    tags = {"UNSYNCEDLYRICS": ["[00:01.00]embedded"]}
    monkeypatch.setattr(mutagen, "File", lambda _: type("Audio", (), {"tags": tags})())

    assert [line.text for line in load_local_lyrics(audio)] == ["embedded"]


def test_loads_embedded_id3_uslt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mutagen = pytest.importorskip("mutagen")
    audio = tmp_path / "song.mp3"
    audio.touch()
    frame = type("USLT", (), {"text": "[00:01.00]embedded"})()
    tags = type("ID3Tags", (), {"getall": lambda self, key: [frame] if key == "USLT" else []})()
    monkeypatch.setattr(mutagen, "File", lambda _: type("Audio", (), {"tags": tags})())

    assert [line.text for line in load_local_lyrics(audio)] == ["embedded"]


def test_loads_embedded_mp4_lyrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mutagen = pytest.importorskip("mutagen")
    audio = tmp_path / "song.m4a"
    audio.touch()
    tags = {"©lyr": ["[00:01.00]embedded"]}
    monkeypatch.setattr(mutagen, "File", lambda _: type("Audio", (), {"tags": tags})())

    assert [line.text for line in load_local_lyrics(audio)] == ["embedded"]


def test_plain_embedded_lyrics_is_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mutagen = pytest.importorskip("mutagen")
    audio = tmp_path / "song.flac"
    audio.touch()
    monkeypatch.setattr(mutagen, "File", lambda _: type("Audio", (), {"tags": {"LYRICS": ["plain text"]}})())

    assert load_local_lyrics(audio) == []


def test_a_root_path_has_no_sidecar_and_does_not_raise():
    # A player publishing xesam:url = "file:///" reaches the loader as Path("/"),
    # where with_suffix raises ValueError rather than the OSError this function
    # handles, so the exception escaped the resolver.
    assert load_local_lyrics(Path("/")) == []


def test_loads_embedded_lyrics_from_a_real_vorbis_comment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # A dict tolerates any key. A real Vorbis comment accepts only printable ASCII
    # and raises on the MP4 key probed alongside it, which used to abort the whole
    # lookup and made every FLAC with embedded lyrics come back empty.
    mutagen = pytest.importorskip("mutagen")
    from mutagen.flac import VCFLACDict

    audio = tmp_path / "song.flac"
    audio.touch()
    tags = VCFLACDict()
    tags["LYRICS"] = ["[00:01.00]embedded"]
    monkeypatch.setattr(mutagen, "File", lambda _: type("Audio", (), {"tags": tags})())

    assert [line.text for line in load_local_lyrics(audio)] == ["embedded"]


def test_a_pipe_where_the_sidecar_should_be_does_not_wedge_the_reader(tmp_path):
    # The path comes from a player. Pointed at a FIFO, read_bytes blocked forever
    # and took a thread-pool worker with it, and the resolver's cancellation could
    # not reclaim it — every retry leaked another worker until the pool was gone.
    import os
    import threading

    audio = tmp_path / "song.flac"
    audio.touch()
    os.mkfifo(tmp_path / "song.lrc")

    finished = threading.Event()

    def read() -> None:
        load_local_lyrics(audio)
        finished.set()

    # Joined rather than left running: if this regresses the thread blocks forever,
    # and an unowned one would sit there for the rest of the session.
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        assert finished.wait(5.0), "the reader is still blocked on a pipe"
    finally:
        reader.join(timeout=5.0)


def test_a_sidecar_larger_than_any_lyric_file_is_read_only_to_the_bound(tmp_path):
    # `is not None` was always true whether or not the read was capped. What the
    # bound actually does is observable at the end of the file: a lyric line past
    # the ceiling is not returned, while the ones before it are.
    from kotonoha.lyrics.local import MAX_SIDECAR_BYTES

    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_bytes(
        b"[00:01.00]near the start\n"
        + b"[00:02.00]" + b"A" * MAX_SIDECAR_BYTES + b"\n"
        + b"[00:03.00]past the ceiling\n"
    )

    texts = [line.text for line in load_local_lyrics(audio)]

    assert "near the start" in texts
    assert "past the ceiling" not in texts, "the whole file was read despite the bound"


def test_a_pipe_where_the_audio_file_should_be_is_not_handed_to_the_tag_reader(tmp_path):
    # The sidecar is not the only player-supplied path: mutagen opens whatever it
    # is given, so the audio path needs the same check. Only the sidecar had a test.
    import os
    import threading

    audio = tmp_path / "song.flac"
    os.mkfifo(audio)
    finished = threading.Event()

    def read() -> None:
        load_local_lyrics(audio)
        finished.set()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        assert finished.wait(5.0), "the tag reader is blocked on a pipe"
    finally:
        reader.join(timeout=5.0)
