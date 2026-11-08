"""Bounded Redis rate gate for verified staff Action inspection and safe dry-run."""

import hashlib

from redis.exceptions import RedisError

from services import shop_admin_security as security

_SCRIPT = """
local blocked = 0
for i = 1, #KEYS do
    local current = redis.call('INCR', KEYS[i])
    if current == 1 then redis.call('EXPIRE', KEYS[i], 60) end
    if current > tonumber(ARGV[i]) then blocked = 1 end
end
return blocked
"""


async def rate_gate(redis, scope, *, dry_run=False):
    """Fail closed on Redis loss; independently bound session, staff and Store load."""
    bucket = "dry" if dry_run else "inspect"
    scopes = [
        f"session:{scope.session_id}:{scope.current_store_id}",
        f"staff:{scope.staff_id}",
        f"store:{scope.current_store_id}",
    ]
    keys = [
        "shop:actions:" + bucket + ":" + hashlib.sha256(item.encode()).hexdigest()
        for item in scopes
    ]
    limits = [15, 30, 60] if dry_run else [120, 240, 600]
    try:
        blocked = await redis.eval(_SCRIPT, 3, *keys, *limits)
    except RedisError:
        raise security.SecurityRejected("security_service_unavailable", 503) from None
    if blocked:
        raise security.SecurityRejected("action_rate_limited", 429)
