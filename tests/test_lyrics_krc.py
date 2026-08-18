import base64
import zlib

from kotonoha.lyrics.krc_parser import KRC_XOR_KEY, parse_krc


def _krc_body(text: str) -> bytes:
    compressed = zlib.compress(text.encode("utf-8"))
    encrypted = bytes(value ^ KRC_XOR_KEY[index % len(KRC_XOR_KEY)] for index, value in enumerate(compressed))
    return b"krc1" + encrypted


def test_parse_krc_decodes_fixture_and_makes_word_times_absolute():
    body = _krc_body("[1200,1000]<0,300,0>先<300,400,0>唱<700,300,0>歌\n")

    lines = parse_krc(body)

    assert len(lines) == 1
    assert lines[0].text == "先唱歌"
    assert lines[0].start == 1.2
    assert lines[0].end == 2.2
    assert [(word.start, word.end) for word in lines[0].words] == [
        (1.2, 1.5),
        (1.5, 1.9),
        (1.9, 2.2),
    ]


def test_parse_krc_rejects_undecodable_body():
    assert parse_krc(base64.b64decode(base64.b64encode(b"not krc"))) == []


def test_a_krc_that_expands_without_bound_is_refused():
    # zlib.decompress allocates whatever the stream unpacks to, and the wire size
    # does not bound that: measured, 203KB of valid compressed body expanded to
    # 200MB and took the process's resident size with it.
    import zlib

    from kotonoha.lyrics.krc_parser import KRC_MAGIC, KRC_XOR_KEY
    from kotonoha.lyrics.payload import MAX_DECOMPRESSED_BYTES

    # A real line first, so an unbounded decoder would return it and this test can
    # tell the two apart; the padding is what the ceiling is there to refuse.
    payload = b"[0,1000]<0,500,0>hello\n" + b"A" * (MAX_DECOMPRESSED_BYTES + 1024)
    bomb = zlib.compress(payload, 9)
    body = KRC_MAGIC + bytes(v ^ KRC_XOR_KEY[i % len(KRC_XOR_KEY)] for i, v in enumerate(bomb))

    assert len(body) < 64 * 1024, "the point is that the wire size is small"
    assert parse_krc(body) == [], "an unbounded expansion was accepted"


def test_an_ordinary_krc_still_decodes():
    import zlib

    from kotonoha.lyrics.krc_parser import KRC_MAGIC, KRC_XOR_KEY

    text = b"[0,1000]<0,500,0>hello<500,500,0> world\n"
    raw = zlib.compress(text, 9)
    body = KRC_MAGIC + bytes(v ^ KRC_XOR_KEY[i % len(KRC_XOR_KEY)] for i, v in enumerate(raw))

    lines = parse_krc(body)

    assert [line.text for line in lines] == ["hello world"]
