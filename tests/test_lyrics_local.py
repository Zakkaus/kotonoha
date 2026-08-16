from pathlib import Path

from kotonoha.lyrics.local import load_sidecar


def test_loads_utf8_sidecar(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("[00:01.00]你好", encoding="utf-8")

    lines = load_sidecar(audio)

    assert [line.text for line in lines] == ["你好"]


def test_loads_gb18030_sidecar(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_bytes("[00:01.00]你好".encode("gb18030"))

    lines = load_sidecar(audio)

    assert [line.text for line in lines] == ["你好"]


def test_missing_sidecar_is_a_miss(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()

    assert load_sidecar(audio) == []


def test_empty_sidecar_is_a_miss(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("", encoding="utf-8")

    assert load_sidecar(audio) == []


def test_untimed_sidecar_is_a_miss(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("[ar:Artist]\n[ti:Song]", encoding="utf-8")

    assert load_sidecar(audio) == []


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

    assert load_sidecar(audio) == []


def test_sidecar_offset_tag_shifts_the_timings(tmp_path: Path):
    # The format's own wording: a "+" offset causes the lyrics to appear sooner,
    # so it comes off each timestamp. A sidecar written against a different rip is
    # commonly a second or two out without it.
    audio = tmp_path / "song.flac"
    audio.touch()
    (tmp_path / "song.lrc").write_text("[offset:+500]\n[00:02.00]line\n", encoding="utf-8")

    assert [line.start for line in load_sidecar(audio)] == [1.5]

    (tmp_path / "song.lrc").write_text("[offset:-500]\n[00:02.00]line\n", encoding="utf-8")
    assert [line.start for line in load_sidecar(audio)] == [2.5]

    # Junk far outside a plausible correction is not an instruction.
    (tmp_path / "song.lrc").write_text("[offset:999999]\n[00:02.00]line\n", encoding="utf-8")
    assert [line.start for line in load_sidecar(audio)] == [2.0]


def test_a_root_path_has_no_sidecar_and_does_not_raise():
    # A player publishing xesam:url = "file:///" reaches the loader as Path("/"),
    # where with_suffix raises ValueError rather than the OSError this function
    # handles, so the exception escaped the resolver.
    assert load_sidecar(Path("/")) == []
