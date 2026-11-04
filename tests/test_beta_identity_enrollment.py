"""Deterministic relational enrollment races without provider or DB servers."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from channels.contracts import Platform
from models.shop_content import ShopIdentity
from models.shop_multibot import DEFAULT_STORE_ID, LEGACY_BOT_IDS, ShopBot
from models.shop_store_commerce import ShopStoreCustomer
from services.shop_identity import register_customer
from tests.schema_support import create_shop_schema, seed_legacy_registry
from tests.test_shared_cart import AsyncDatabase


@pytest.fixture
def enrollment_engine(tmp_path):
    """Keep competing SQLAlchemy sessions on the same disposable database."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'enrollment.db'}")
    create_shop_schema(engine)
    with Session(engine) as session:
        seed_legacy_registry(session)
        session.add(ShopBot(
            id="telegram-second", store_id=DEFAULT_STORE_ID,
            slug="telegram-second", name="Second Telegram",
            platform="telegram", status="legacy", runtime_owner="legacy",
            credential_version=1, version=1,
        ))
        session.commit()
    yield engine
    engine.dispose()


class RegistrationAfterMissingRead(AsyncDatabase):
    """Commit a real competing registration after the first identity SELECT.

    Both requests observe a missing identity before the losing request flushes.
    No database error is fabricated: the real unique constraint detects the
    collision, making the failing schedule repeatable without timing sleeps.
    """

    def __init__(self, session, winner_session, platform):
        """Hold isolated losing/winning sessions and the tested provider."""
        super().__init__(session)
        self.winner_session = winner_session
        self.platform = platform
        self.winner = None

    async def execute(self, statement):
        """Finish the missing SELECT before allowing the winner to commit."""
        result = await super().execute(statement)
        if self.winner is None:
            # Materialize the real empty result so SQLite's SELECT cursor is
            # closed before another connection performs the competing write.
            result = result.freeze()()
            self.winner = await register_customer(
                AsyncDatabase(self.winner_session), platform=self.platform,
                platform_user_id=101, first_name="Winning customer",
            )
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_parallel_first_start_reuses_winner_without_orphan(
    enrollment_engine, platform,
):
    """A duplicate first /start returns the winner and rolls back its customer."""
    with (
        Session(enrollment_engine) as losing_session,
        Session(enrollment_engine) as winning_session,
    ):
        race = RegistrationAfterMissingRead(
            losing_session, winning_session, platform,
        )
        identity = await register_customer(
            race, platform=platform, platform_user_id=101,
            first_name="Losing customer",
        )
        assert identity.id == race.winner.id
        assert identity.customer_id == race.winner.customer_id
        assert identity.bot_id == LEGACY_BOT_IDS[platform.value]
        assert identity.allow_announcements is False
        assert losing_session.is_active
    with Session(enrollment_engine) as verification:
        identities = verification.scalars(select(ShopIdentity)).all()
        customers = verification.scalars(select(ShopStoreCustomer)).all()
        assert len(identities) == 1
        assert len(customers) == 1
        assert customers[0].id == identities[0].customer_id


@pytest.mark.asyncio
async def test_equal_numeric_ids_create_independent_bot_customers(enrollment_engine):
    """Two Telegram bots and Bale cannot merge an unverified numeric ID."""
    with Session(enrollment_engine) as session:
        db = AsyncDatabase(session)
        owners = []
        for platform, bot_id in (
            (Platform.TELEGRAM, LEGACY_BOT_IDS["telegram"]),
            (Platform.TELEGRAM, "telegram-second"),
            (Platform.BALE, LEGACY_BOT_IDS["bale"]),
        ):
            identity = await register_customer(
                db, platform=platform, platform_user_id=101,
                bot_id=bot_id,
            )
            owners.append((identity.id, identity.customer_id))
        assert len({identity_id for identity_id, _ in owners}) == 3
        assert len({customer_id for _, customer_id in owners}) == 3
        repeated = await register_customer(
            db, platform=Platform.TELEGRAM, platform_user_id=101,
            bot_id="telegram-second", first_name="Updated customer",
        )
        assert (repeated.id, repeated.customer_id) == owners[1]
        assert repeated.first_name == "Updated customer"
        assert session.query(ShopStoreCustomer).count() == 3


@pytest.mark.asyncio
async def test_preloaded_legacy_identity_keeps_competing_customer_attachment(
    enrollment_engine,
):
    """A stale ORM identity must not overwrite a just-committed attachment."""
    with Session(enrollment_engine) as seed:
        legacy = ShopIdentity(
            bot_id=LEGACY_BOT_IDS["telegram"], store_id=DEFAULT_STORE_ID,
            platform="telegram", platform_user_id=101,
        )
        seed.add(legacy)
        seed.commit()
        identity_id = legacy.id
    with (
        Session(enrollment_engine) as losing_session,
        Session(enrollment_engine) as winning_session,
    ):
        # Keep the pre-race row alive in this session's real identity map.
        preloaded = losing_session.get(ShopIdentity, identity_id)
        assert preloaded.customer_id is None
        winner = await register_customer(
            AsyncDatabase(winning_session), platform=Platform.TELEGRAM,
            platform_user_id=101,
        )
        winning_customer_id = winner.customer_id
        recovered = await register_customer(
            AsyncDatabase(losing_session), platform=Platform.TELEGRAM,
            platform_user_id=101,
        )
        assert recovered.customer_id == winning_customer_id
    with Session(enrollment_engine) as verification:
        assert verification.query(ShopIdentity).count() == 1
        assert verification.query(ShopStoreCustomer).count() == 1


@pytest.mark.asyncio
async def test_unrelated_constraint_failure_is_not_a_cross_bot_registration(
    enrollment_engine,
):
    """Recovery must rethrow another DB error without borrowing another Bot ID."""
    with Session(enrollment_engine) as session:
        db = AsyncDatabase(session)
        await register_customer(
            db, platform=Platform.TELEGRAM, platform_user_id=101,
            bot_id="telegram-second",
        )
        # Simulate a separate database invariant using a real SQLite trigger;
        # the unique identity race remains the only safely recoverable error.
        session.execute(text(
            "CREATE TRIGGER reject_customer BEFORE INSERT ON shop_identities "
            "WHEN NEW.first_name = 'Rejected customer' "
            "BEGIN SELECT RAISE(ABORT, 'test_identity_invariant'); END"
        ))
        session.commit()
        with pytest.raises(IntegrityError, match="test_identity_invariant"):
            await register_customer(
                db, platform=Platform.TELEGRAM, platform_user_id=101,
                first_name="Rejected customer",
            )
        await db.rollback()
        assert session.query(ShopIdentity).count() == 1
        assert session.query(ShopStoreCustomer).count() == 1
