"""Stable identity rules for the reusable attribute catalog and its backfill."""

import hashlib
import json
import unicodedata

_VARIANTS = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "\u200c": " ",
    **dict(zip("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)),
})


def _canonical(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(_VARIANTS).casefold().split())


def _signature(parts: list) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def definition_signature_v1(label: str, unit: str | None, aliases: list[str], external_ids: dict) -> str:
    """Normalize display variants without merging conflicting source records."""
    return _signature([_canonical(label), _canonical(unit or ""), sorted({_canonical(a) for a in aliases}), external_ids])


def term_signature_v1(label: str, external_ids: dict) -> str:
    """Compare term labels within one definition."""
    return _signature([_canonical(label), external_ids])
