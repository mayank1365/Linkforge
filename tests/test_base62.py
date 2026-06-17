from app.base62 import decode, encode


def test_roundtrip():
    for n in (0, 1, 61, 62, 63, 100_000, 123_456_789):
        assert decode(encode(n)) == n


def test_encode_is_url_safe():
    code = encode(123_456_789)
    assert code.isalnum()


def test_distinct_ids_distinct_codes():
    codes = {encode(i) for i in range(1000)}
    assert len(codes) == 1000


def test_zero():
    assert encode(0) == "0"
    assert decode("0") == 0
