"""Single authoritative product/category entitlement policy for each bot.

Precedence: unpublished product -> deny; explicit product deny -> deny;
explicit product allow -> allow; category deny -> deny; category allow ->
allow; otherwise legacy bots allow and new registry bots deny.

Both catalog pagination and payment/cart paths use this same SQL expression,
so stale callbacks cannot bypass a hidden product's permissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import and_, false, literal, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from models.shop_bot_catalog_acl import (
    ShopBotCatalogAudit,
    ShopBotCategoryRule,
    ShopBotProductRule,
)
from models.shop_content import Product, ShopCategory
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    DEFAULT_STORE_ID, LEGACY_BOT_IDS, ShopBot, ShopBotRegistryEvent, ShopStore,
)
from services import shop_admin_security as security

RULE_EFFECTS = frozenset({"allow", "deny", "inherit"})
RULE_OBJECTS = {
    "product": (ShopBotProductRule, Product, "product_id"),
    "category": (ShopBotCategoryRule, ShopCategory, "category_id"),
}


@dataclass(frozen=True, slots=True)
class CatalogScope:
    """Authenticated bot policy, with separate runtime and preview readiness."""

    bot_id: str
    store_id: str
    default_allow: bool
    available: bool


def legacy_bot_id(platform: str) -> str:
    """Map only authenticated legacy Telegram/Bale adapters to immutable IDs."""
    bot_id = LEGACY_BOT_IDS.get(platform)
    if bot_id is None:
        raise security.SecurityRejected("invalid_bot_platform", 422)
    return bot_id


async def resolve_scope(
    db: AsyncSession, *, bot_id: str, preview: bool = False,
) -> CatalogScope:
    """Read a bot's store/registration and never grant another store catalog."""
    bot = await db.get(ShopBot, bot_id)
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    store = await db.get(ShopStore, bot.store_id)
    available = bool(
        store is not None and store.state == "active"
        and bot.store_id == DEFAULT_STORE_ID
    )
    if not preview:
        available = available and (
            (bot.status == "legacy" and bot.runtime_owner == "legacy")
            or (bot.status == "active" and bot.runtime_owner == "registry")
        )
        policy = await db.get(ShopBotOperations, bot.id)
        if policy is not None and policy.desired_state != "active":
            available = False
    return CatalogScope(
        bot_id=bot.id,
        store_id=bot.store_id,
        default_allow=(
            bot.status == "legacy" and bot.runtime_owner == "legacy"
        ),
        available=available,
    )


async def resolve_legacy_scope(db: AsyncSession, platform: str) -> CatalogScope:
    """Resolve the actual legacy bot, never infer it from callback parameters."""
    bot_id = legacy_bot_id(platform)
    scope = await resolve_scope(db, bot_id=bot_id)
    if not scope.default_allow:
        raise security.SecurityRejected("invalid_bot_runtime", 409)
    return scope


def permitted_product_clause(scope: CatalogScope):
    """Generate a correlated SQL predicate used by every catalog read.

    The same predicate filters both paginated SQL lists and single products.
    An allow on a product overrides a deny on its category, but an explicit
    product deny is final. No client data is evaluated as SQL source text.
    """
    if not scope.available:
        return false()

    product_deny = select(ShopBotProductRule.product_id).where(
        ShopBotProductRule.bot_id == scope.bot_id,
        ShopBotProductRule.product_id == Product.id,
        ShopBotProductRule.effect == "deny",
    ).correlate(Product).exists()
    product_allow = select(ShopBotProductRule.product_id).where(
        ShopBotProductRule.bot_id == scope.bot_id,
        ShopBotProductRule.product_id == Product.id,
        ShopBotProductRule.effect == "allow",
    ).correlate(Product).exists()
    category_deny = select(ShopBotCategoryRule.category_id).where(
        ShopBotCategoryRule.bot_id == scope.bot_id,
        ShopBotCategoryRule.category_id == Product.category_id,
        ShopBotCategoryRule.effect == "deny",
    ).correlate(Product).exists()
    category_allow = select(ShopBotCategoryRule.category_id).where(
        ShopBotCategoryRule.bot_id == scope.bot_id,
        ShopBotCategoryRule.category_id == Product.category_id,
        ShopBotCategoryRule.effect == "allow",
    ).correlate(Product).exists()

    return and_(
        Product.is_published.is_(True),
        not_(product_deny),
        or_(
            product_allow,
            and_(
                not_(category_deny),
                or_(category_allow, literal(scope.default_allow)),
            ),
        ),
    )


async def visible_product_ids(
    db: AsyncSession, scope: CatalogScope, ids: list[int] | set[int],
) -> set[int]:
    """Return accessible published IDs in one query without an N+1 lookup."""
    identifiers = set(ids)
    if not identifiers or not scope.available:
        return set()
    result = await db.scalars(select(Product.id).where(
        Product.id.in_(identifiers),
        permitted_product_clause(scope),
    ))
    return set(result.all())


async def lock_bot_catalog_policy(
    db: AsyncSession, bot_id: str,
) -> None:
    """Serialize payment/order creation with any per-bot ACL edit."""
    owned = await db.scalar(select(ShopBot.id).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    if owned is None:
        raise security.SecurityRejected("bot_not_found", 404)


async def lock_legacy_catalog_policy(
    db: AsyncSession, platform: str,
) -> None:
    """Serialize final order/payment creation against ACL policy edits.

    All administrative rule updates lock the ShopBot row first. Locking the
    same row in the transaction that creates an order or invoice ensures the
    policy cannot be changed between the final eligibility check and commit.
    """
    bot_id = legacy_bot_id(platform)
    existing = await db.scalar(select(ShopBot.id).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    if existing is None:
        raise security.SecurityRejected("bot_not_found", 404)


async def allowed_for_bot(
    db: AsyncSession, bot_id: str, product_ids: list[int] | set[int],
) -> bool:
    """Re-evaluate every current product grant in the authenticated bot scope."""
    identifiers = set(product_ids)
    if not identifiers:
        return False
    scope = await resolve_scope(db, bot_id=bot_id)
    permitted = await visible_product_ids(db, scope, identifiers)
    return permitted == identifiers


async def allowed_for_legacy(
    db: AsyncSession, platform: str, product_ids: list[int] | set[int],
) -> bool:
    """Deny a cart or invoice when any line no longer belongs to this bot."""
    identifiers = set(product_ids)
    if not identifiers:
        return False
    scope = await resolve_legacy_scope(db, platform)
    authorized = await visible_product_ids(db, scope, identifiers)
    return identifiers == authorized


def _check_rule_request(
    *, object_type: str, identifiers: list[int], effect: str,
) -> list[int]:
    """Validate limited, unique positive target IDs without accepting booleans."""
    if object_type not in RULE_OBJECTS or effect not in RULE_EFFECTS:
        raise security.SecurityRejected("invalid_catalog_rule", 422)
    if (
        not isinstance(identifiers, list)
        or not 1 <= len(identifiers) <= 100
        or any(type(value) is not int or value <= 0 for value in identifiers)
        or len(set(identifiers)) != len(identifiers)
    ):
        raise security.SecurityRejected("invalid_catalog_rule", 422)
    return sorted(identifiers)


def _check_bot(db: Session, bot_id: str, expected_version: int | None) -> ShopBot:
    """Lock a bot row to serialize all ACL changes and validate store scope."""
    bot = db.scalar(select(ShopBot).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    if bot.store_id != DEFAULT_STORE_ID:
        raise security.SecurityRejected("catalog_store_not_ready", 409)
    if expected_version is not None and bot.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    return bot


def _apply_changes(
    db: Session, *, bot: ShopBot, actor_id: int,
    object_type: str, target_ids: list[int], effect: str,
) -> int:
    """Apply/clear explicit M2M rules and append one audit per changed target."""
    rule_model, item_model, id_name = RULE_OBJECTS[object_type]
    available_ids = set(db.scalars(select(item_model.id).where(
        item_model.id.in_(target_ids),
    )).all())
    if len(available_ids) != len(target_ids):
        raise security.SecurityRejected("catalog_target_not_found", 404)

    records = db.scalars(select(rule_model).where(
        rule_model.bot_id == bot.id,
        getattr(rule_model, id_name).in_(target_ids),
    ).with_for_update()).all()
    indexed = {getattr(row, id_name): row for row in records}
    changed = 0
    for target_id in target_ids:
        existing = indexed.get(target_id)
        previous = existing.effect if existing is not None else "inherit"
        if previous == effect:
            continue
        if effect == "inherit":
            db.delete(existing)
        elif existing is None:
            db.add(rule_model(
                bot_id=bot.id, **{id_name: target_id},
                effect=effect, updated_by=actor_id,
            ))
        else:
            existing.effect = effect
            existing.updated_by = actor_id
        db.add(ShopBotCatalogAudit(
            id=str(uuid4()), bot_id=bot.id,
            object_type=object_type, object_id=target_id,
            old_effect=previous, new_effect=effect,
            actor_id=actor_id,
        ))
        changed += 1
    if changed:
        bot.version += 1
        db.add(ShopBotRegistryEvent(
            id=str(uuid4()), bot_id=bot.id,
            actor_id=actor_id, action="bot_updated",
        ))
        security.audit(db, actor_id, "bots.catalog_rules_changed", bot.id)
    return changed


def update_bot_rules(
    db: Session, *, bot_id: str, actor_id: int,
    expected_version: int | None, object_type: str,
    target_ids: list[int], effect: str,
) -> int:
    """Change up to 100 rules atomically; always retain immutable audit."""
    targets = _check_rule_request(
        object_type=object_type, identifiers=target_ids, effect=effect,
    )
    bot = _check_bot(db, bot_id, expected_version)
    return _apply_changes(
        db, bot=bot, actor_id=actor_id,
        object_type=object_type, target_ids=targets, effect=effect,
    )


def update_product_bot_rules(
    db: Session, *, product_id: int, actor_id: int,
    assignments: list[tuple[str, str, int]],
) -> int:
    """Apply M2M assignments from the Product Editor in one transaction.

    Only explicitly supplied bot IDs are modified; unselected bots and
    published product data remain untouched. Bot locks are ordered by ID.
    """
    if (
        type(product_id) is not int or product_id <= 0
        or not assignments or len(assignments) > 100
        or any(
            effect not in RULE_EFFECTS
            or not isinstance(bot_id, str)
            or type(version) is not int or version <= 0
            for bot_id, effect, version in assignments
        )
        or len(set(bot_id for bot_id, _, _ in assignments)) != len(assignments)
    ):
        raise security.SecurityRejected("invalid_catalog_rule", 422)
    if db.get(Product, product_id) is None:
        raise security.SecurityRejected("catalog_target_not_found", 404)
    bot_ids = [bot_id for bot_id, _, _ in assignments]
    bots = {
        bot.id: bot for bot in db.scalars(select(ShopBot).where(
            ShopBot.id.in_(bot_ids),
        ).order_by(ShopBot.id).with_for_update()).all()
    }
    if len(bots) != len(assignments):
        raise security.SecurityRejected("bot_not_found", 404)
    total = 0
    for bot_id, effect, expected_version in sorted(assignments):
        bot = bots[bot_id]
        if bot.version != expected_version:
            raise security.SecurityRejected("configuration_changed", 409)
        if bot.store_id != DEFAULT_STORE_ID:
            raise security.SecurityRejected("catalog_store_not_ready", 409)
        total += _apply_changes(
            db, bot=bot, actor_id=actor_id,
            object_type="product", target_ids=[product_id], effect=effect,
        )
    return total
