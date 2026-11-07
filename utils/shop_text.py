"""Normalize untrusted human text before storing it in the shop."""

import unicodedata

_JOINERS = frozenset({"\u200c", "\u200d"})
_UNPRINTABLE = frozenset({"Cc", "Cf", "Cs"})


def clean_text(value: str, *, multiline: bool = False) -> str:
    """Drop control and direction overrides while preserving Persian joiners.

    This handles plain text only. Render the result as text or escape it for
    the output context. Do not use it to transform credentials, IDs or URLs.
    """
    value = (
        value.replace("\r\n", "\n").replace("\r", "\n")
        .replace("\u2028", "\n").replace("\u2029", "\n")
    )
    result = []
    for char in value:
        if char in "\n\t":
            result.append(char if multiline else " ")
        elif char in _JOINERS or unicodedata.category(char) not in _UNPRINTABLE:
            result.append(char)
    cleaned = unicodedata.normalize("NFC", "".join(result)).strip()
    return cleaned if any(char not in _JOINERS and not char.isspace() for char in cleaned) else ""
