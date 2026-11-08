"""Bounded Action metrics and structured logs containing only safe metadata."""

import logging
from collections import Counter

_LOG = logging.getLogger("shop.actions")
_COUNTERS: Counter = Counter()


def observe(spec, principal, result, *, deduplicated=False) -> None:
    """Record fixed descriptor labels without raw payloads, keys or proof tokens."""
    descriptor = spec.descriptor if spec else None
    labels = (
        descriptor.key if descriptor else "unknown",
        descriptor.version if descriptor else "unknown",
        principal.platform,
        descriptor.side_effect if descriptor else "none",
        result.status,
        result.error.code if result.error else "none",
    )
    _COUNTERS[("invocations", *labels)] += 1
    _COUNTERS[("duration_ms", *labels)] += result.duration_ms
    if result.retry_count:
        _COUNTERS[("retry", *labels)] += 1
    if deduplicated:
        _COUNTERS[("deduplicated", *labels)] += 1
    _LOG.info(
        "action.completed",
        extra={
            "action_key": labels[0],
            "action_version": labels[1],
            "platform": labels[2],
            "side_effect": labels[3],
            "status": labels[4],
            "error_code": labels[5],
            "store_id": principal.store_id,
            "bot_id": principal.bot_id,
            "correlation_id": result.correlation_id,
            "duration_ms": result.duration_ms,
            "retry_count": result.retry_count,
            "deduplicated": deduplicated,
        },
    )


def snapshot() -> dict:
    """Return current process counters for aggregation by monitoring adapters."""
    return dict(_COUNTERS)
