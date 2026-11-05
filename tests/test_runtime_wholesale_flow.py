"""The real Registry completes a fully typed form without a live provider."""

import pytest
from sqlalchemy import select, func
from tests.test_action_security import buyer, db
from tests.test_runtime_sessions import setup_runtime, inbound
from tests.test_runtime_workers import factory
from models.shop_workflow_runtime import WorkflowRun, WorkflowOutbox
from models.shop_wholesale import ShopWholesaleApplication
from models.shop_action import ShopActionExecution
from services.shop_runtime.contracts import RuntimeInput, publication_findings
from services.shop_runtime.sessions import handle
from services.shop_runtime.workers import action_once
from services.shop_workflow_templates import wholesale_application_template
from services.shop_workflow_validation import validate_definition


def test_wholesale_template_is_publishable_and_simulator_has_no_unresolved_action():
    """The mandatory example uses only real available Actions and bounded primitives."""
    definition, _ = wholesale_application_template()
    report = validate_definition(definition)
    assert report.valid, [x.model_dump() for x in report.issues]
    assert publication_findings(definition) == []


@pytest.mark.asyncio
async def test_whole_form_persists_once_with_exact_customer_confirmation(
    buyer, monkeypatch
):
    """Typed form values reach the real domain once, through one stable Action receipt."""
    connection, principal = buyer
    definition, _ = wholesale_application_template()
    await setup_runtime(connection, principal, monkeypatch, definition)
    for n, text in [(1, "/wholesale"), (2, "Alice QA")]:
        await handle(
            connection,
            context=principal.bot,
            event=inbound(n, text, "command" if n == 1 else "text"),
        )
    await handle(
        connection,
        context=principal.bot,
        event=RuntimeInput(
            platform="telegram",
            update_id="3",
            user_id=101,
            chat_id=101,
            kind="contact",
            text="+989121234567",
            contact_owner=101,
        ),
    )
    for n, text in [(4, "QA Company"), (5, "QA City"), (6, "۱۲۰۰۰۰"), (7, "/skip")]:
        await handle(
            connection,
            context=principal.bot,
            event=inbound(n, text, "command" if n == 7 else "text"),
        )
    out = (
        await connection.scalars(
            select(WorkflowOutbox).order_by(WorkflowOutbox.sequence.desc())
        )
    ).first()
    token = out.payload["buttons"][0]["callback_data"]
    event = RuntimeInput(
        platform="telegram",
        update_id="8",
        user_id=101,
        chat_id=101,
        kind="callback",
        callback=token,
    )
    await handle(connection, context=principal.bot, event=event)
    await action_once(factory(connection))
    connection.session.expire_all()
    run = await connection.scalar(select(WorkflowRun))
    assert run.status == "completed", run.error_code
    application = await connection.scalar(select(ShopWholesaleApplication))
    assert (
        application.name,
        application.phone,
        application.company,
        application.city,
        application.estimated_monthly_amount,
    ) == ("Alice QA", "+989121234567", "QA Company", "QA City", 120000)
    assert (
        application.document_handle is None
        and application.customer_id == principal.customer_id
    )
    await handle(connection, context=principal.bot, event=event)
    await action_once(factory(connection))
    assert (
        await connection.scalar(
            select(func.count()).select_from(ShopWholesaleApplication)
        )
        == 1
    )
    assert (
        await connection.scalar(select(func.count()).select_from(ShopActionExecution))
        == 1
    )
