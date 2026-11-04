"""Expired CRM restrictions restore scoped account and order access."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, aliased

from channels.contracts import Platform
from models.shop_content import Product, ShopIdentity, ShopOrder
from models.shop_customer_crm import ShopCustomerAudit, ShopCustomerProfile
from models.shop_multibot import DEFAULT_STORE_ID, LEGACY_BOT_IDS, ShopBot
from models.shop_staff import ShopStaff
from models.shop_store_commerce import ShopStoreCustomer
from services.shop_bot_context import BotContext
from services.shop_customer_account import customer_for_bot
from services.shop_customer_orders import (
    order_visible_to_customer,
    verified_identity_keys,
)
from tests.schema_support import create_shop_schema, seed_legacy_registry
from tests.test_shared_cart import AsyncDatabase


@pytest.fixture
def access_lab():
    """Create linked identities with expired, active and permanent bans."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as session:
        seed_legacy_registry(session)
        session.add(
            ShopStaff(
                id=1,
                username="expiry-reviewer",
                password_hash="offline-only",
                role="superadmin",
                is_active=True,
            )
        )
        customers = [
            ShopStoreCustomer(store_id=DEFAULT_STORE_ID, display_name=name)
            for name in ("Linked customer", "Other customer")
        ]
        session.add_all(customers)
        session.flush()
        other_bot = ShopBot(
            id=str(uuid4()),
            store_id=DEFAULT_STORE_ID,
            slug="other-telegram",
            name="Other Telegram",
            platform="telegram",
            status="legacy",
            runtime_owner="legacy",
        )
        product = Product(
            store_id=DEFAULT_STORE_ID,
            sku="EXPIRY-ORDER",
            name="Order item",
            description="Ownership fixture",
            price=100,
            stock_quantity=10,
            product_type="physical",
            requires_shipping=True,
        )
        session.add_all([other_bot, product])
        session.flush()
        records = {}
        profiles = {}
        orders = {}
        for name, platform, user_id, blocked, expiry in (
            ("expired_tg", "telegram", 101, True, now - timedelta(days=1)),
            ("expired_bale", "bale", 101, True, now - timedelta(days=1)),
            ("future", "telegram", 202, True, now + timedelta(days=1)),
            ("permanent", "telegram", 303, True, None),
            ("missing_profile", "telegram", 404, True, None),
            ("clear", "telegram", 505, False, None),
            (
                "clear_with_expiry",
                "telegram",
                606,
                False,
                now + timedelta(days=1),
            ),
            ("other_customer", "telegram", 101, False, None),
        ):
            identity = ShopIdentity(
                store_id=DEFAULT_STORE_ID,
                bot_id=(
                    other_bot.id
                    if name == "other_customer"
                    else LEGACY_BOT_IDS[platform]
                ),
                platform=platform,
                platform_user_id=user_id,
                customer_id=customers[name == "other_customer"].id,
                is_blocked=blocked,
            )
            session.add(identity)
            session.flush()
            records[name] = identity
            if name not in {"missing_profile", "clear", "other_customer"}:
                profile = ShopCustomerProfile(
                    identity_id=identity.id,
                    restriction_until=expiry,
                    restriction_reason="Documented temporary restriction",
                    restricted_by=1,
                    restricted_at=now - timedelta(days=2),
                )
                profiles[name] = profile
                session.add(profile)
                session.add(
                    ShopCustomerAudit(
                        identity_id=identity.id,
                        actor_id=1,
                        action="restricted",
                        reason="Original immutable restriction evidence",
                    )
                )
            order = ShopOrder(
                store_id=DEFAULT_STORE_ID,
                bot_id=identity.bot_id,
                platform=platform,
                platform_user_id=user_id,
                chat_id=user_id,
                product_id=product.id,
                product_name_snapshot=product.name,
                quantity=1,
                unit_price_irr=100,
                total_irr=100,
                provider="bale_wallet"
                if platform == "bale"
                else "telegram_fiat",
                status="pending_payment",
                invoice_payload=uuid4().hex,
            )
            session.add(order)
            orders[name] = order
        session.commit()
        contexts = {
            platform: BotContext(
                bot_id=LEGACY_BOT_IDS[platform.value],
                store_id=DEFAULT_STORE_ID,
                platform=platform,
                provider_bot_id=None,
                status="legacy",
                runtime_owner="legacy",
                credential_version=1,
                registry_version=1,
            )
            for platform in (Platform.TELEGRAM, Platform.BALE)
        }
        yield SimpleNamespace(
            session=session,
            db=AsyncDatabase(session),
            now=now,
            customer=customers[0],
            contexts=contexts,
            identities=records,
            profiles=profiles,
            orders=orders,
        )
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "identity_name"),
    [(Platform.TELEGRAM, "expired_tg"), (Platform.BALE, "expired_bale")],
)
async def test_expired_restriction_restores_exact_account(
    access_lab,
    platform,
    identity_name,
):
    """An expired raw block cannot send a known customer back to /start."""
    identity, customer = await customer_for_bot(
        access_lab.db,
        access_lab.contexts[platform],
        platform_user_id=101,
    )
    assert identity.id == access_lab.identities[identity_name].id
    assert customer.id == access_lab.customer.id
    assert identity.is_blocked is True


@pytest.mark.asyncio
async def test_verified_keys_include_expired_but_exclude_live_restrictions(
    access_lab,
):
    """Expiry restores eligibility within the verified customer links."""
    keys = await verified_identity_keys(
        access_lab.db,
        store_id=DEFAULT_STORE_ID,
        customer_id=access_lab.customer.id,
    )
    assert set(keys) == {
        (LEGACY_BOT_IDS["telegram"], "telegram", 101),
        (LEGACY_BOT_IDS["bale"], "bale", 101),
        (LEGACY_BOT_IDS["telegram"], "telegram", 505),
        (LEGACY_BOT_IDS["telegram"], "telegram", 606),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("identity_name", ["expired_tg", "expired_bale"])
async def test_expired_identity_can_read_its_original_order(
    access_lab, identity_name
):
    """The effective identity tuples unlock only their own historical order."""
    order = access_lab.orders[identity_name]
    visible = await order_visible_to_customer(
        access_lab.db,
        store_id=DEFAULT_STORE_ID,
        customer_id=access_lab.customer.id,
        order_id=order.id,
    )
    assert visible is not None and visible.id == order.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity_name", ["future", "permanent", "missing_profile"]
)
async def test_live_or_unexpiring_restriction_stays_denied(
    access_lab, identity_name
):
    """Missing expiry evidence cannot weaken an active restriction."""
    identity = access_lab.identities[identity_name]
    with pytest.raises(ValueError):
        await customer_for_bot(
            access_lab.db,
            access_lab.contexts[Platform.TELEGRAM],
            platform_user_id=identity.platform_user_id,
        )
    assert (
        await order_visible_to_customer(
            access_lab.db,
            store_id=DEFAULT_STORE_ID,
            customer_id=access_lab.customer.id,
            order_id=access_lab.orders[identity_name].id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_equal_user_number_on_other_bot_does_not_grant_orders(
    access_lab,
):
    """Equal user numbers on another Bot cannot grant linked access."""
    assert (
        await order_visible_to_customer(
            access_lab.db,
            store_id=DEFAULT_STORE_ID,
            customer_id=access_lab.customer.id,
            order_id=access_lab.orders["other_customer"].id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_shared_guard_matches_effective_restriction_policy(access_lab):
    """SQL and loaded-row callers share one exact restriction decision."""
    from services.shop_customer_access import customer_access_allowed

    allowed = {
        name: await customer_access_allowed(
            access_lab.db,
            identity,
            now=access_lab.now,
        )
        for name, identity in access_lab.identities.items()
    }
    assert allowed == {
        "expired_tg": True,
        "expired_bale": True,
        "future": False,
        "permanent": False,
        "missing_profile": False,
        "clear": True,
        "clear_with_expiry": True,
        "other_customer": True,
    }


@pytest.mark.asyncio
async def test_expiry_boundary_is_inclusive_and_utc_normalized(access_lab):
    """Expiry releases the restriction exactly at its stored UTC instant."""
    from services.shop_customer_access import customer_access_allowed

    identity = access_lab.identities["expired_tg"]
    access_lab.profiles["expired_tg"].restriction_until = access_lab.now
    access_lab.session.commit()
    assert (
        await customer_access_allowed(
            access_lab.db,
            identity,
            now=access_lab.now - timedelta(microseconds=1),
        )
        is False
    )
    assert (
        await customer_access_allowed(
            access_lab.db,
            identity,
            now=access_lab.now,
        )
        is True
    )
    assert (
        await customer_access_allowed(
            access_lab.db,
            identity,
            now=access_lab.now.replace(tzinfo=None),
        )
        is True
    )


def test_sql_access_clause_correlates_alias_inside_profile_join(access_lab):
    """A joined profile cannot erase or broaden the exact expiry subquery."""
    from services.shop_customer_access import customer_access_clause

    identity = aliased(ShopIdentity)
    query = (
        select(identity.id)
        .outerjoin(
            ShopCustomerProfile,
            ShopCustomerProfile.identity_id == identity.id,
        )
        .where(
            identity.store_id == DEFAULT_STORE_ID,
            identity.customer_id == access_lab.customer.id,
            customer_access_clause(now=access_lab.now, identity=identity),
        )
    )
    assert set(access_lab.session.scalars(query)) == {
        access_lab.identities[name].id
        for name in (
            "expired_tg",
            "expired_bale",
            "clear",
            "clear_with_expiry",
        )
    }


@pytest.mark.asyncio
async def test_loaded_row_guard_uses_current_restriction_not_cached_flag(
    access_lab,
):
    """A stale unblocked object cannot bypass the current restriction."""
    from services.shop_customer_access import customer_access_allowed

    identity = access_lab.identities["clear_with_expiry"]
    access_lab.session.execute(
        update(ShopIdentity)
        .where(
            ShopIdentity.id == identity.id,
        )
        .values(is_blocked=True)
        .execution_options(synchronize_session=False)
    )
    access_lab.session.commit()
    assert identity.is_blocked is False
    assert (
        await customer_access_allowed(
            access_lab.db,
            identity,
            now=access_lab.now,
        )
        is False
    )


@pytest.mark.asyncio
async def test_missing_identity_cannot_gain_access_from_its_raw_flag(
    access_lab,
):
    """A nonpersisted or missing identity is never an eligible recipient."""
    from services.shop_customer_access import customer_access_allowed

    assert await customer_access_allowed(access_lab.db, None) is False
    unpersisted = ShopIdentity(
        id=987654321,
        store_id=DEFAULT_STORE_ID,
        bot_id=LEGACY_BOT_IDS["telegram"],
        platform="telegram",
        platform_user_id=919,
        is_blocked=False,
    )
    assert await customer_access_allowed(access_lab.db, unpersisted) is False


@pytest.mark.asyncio
async def test_expired_access_preserves_restriction_and_audit_evidence(
    access_lab,
):
    """Eligibility reads preserve all restriction and audit evidence."""
    from services.shop_customer_access import customer_access_allowed

    profile = access_lab.profiles["expired_tg"]
    original = (
        profile.restriction_reason,
        profile.restriction_until,
        profile.restricted_by,
        profile.restricted_at,
    )
    audit = list(access_lab.session.scalars(select(ShopCustomerAudit)))
    original_audit = [(row.id, row.action, row.reason) for row in audit]
    identity = access_lab.identities["expired_tg"]
    assert await customer_access_allowed(access_lab.db, identity) is True
    await customer_for_bot(
        access_lab.db,
        access_lab.contexts[Platform.TELEGRAM],
        platform_user_id=101,
    )
    await verified_identity_keys(
        access_lab.db,
        store_id=DEFAULT_STORE_ID,
        customer_id=access_lab.customer.id,
    )
    assert identity.is_blocked is True
    assert original == (
        profile.restriction_reason,
        profile.restriction_until,
        profile.restricted_by,
        profile.restricted_at,
    )
    assert original_audit == [
        (row.id, row.action, row.reason)
        for row in access_lab.session.scalars(select(ShopCustomerAudit))
    ]
    assert not access_lab.session.new
    assert not access_lab.session.dirty
    assert not access_lab.session.deleted
