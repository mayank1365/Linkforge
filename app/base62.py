"""Base62 encoding for compact, URL-safe short codes derived from row ids."""

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)


def encode(num: int) -> str:
    if num < 0:
        raise ValueError("cannot encode negative numbers")
    if num == 0:
        return ALPHABET[0]
    chars = []
    while num > 0:
        num, rem = divmod(num, BASE)
        chars.append(ALPHABET[rem])
    return "".join(reversed(chars))


def decode(code: str) -> int:
    num = 0
    for ch in code:
        num = num * BASE + ALPHABET.index(ch)
    return num
