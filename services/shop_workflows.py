"""Shared Studio persistence services for the dashboard and future MCP adapters.

Every public operation requires a trusted actor and StoreContext. Snapshots are
portable, immutable evidence; live dispatch and business executors are absent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from models.shop_workflow import ShopWorkflow, ShopWorkflowRevision
from services import shop_admin_security as security
from services.shop_workflow_bindings import authorize, validate_bindings
from services.shop_workflow_schema import (
    Definition,
    EditorLayout,
    canonical_json,
)
from services.shop_workflow_requests import (
    CreateDraft,
    DuplicateDraft,
    Operation,
    RestoreDraft,
    SaveDraft,
    ValidateDraft,
    checked_payload,
)
from services.shop_workflow_validation import validate_definition


def _hash(value: str) -> str:
    """Hash exact canonical UTF-8 bytes without logging definition content."""
    return hashlib.sha256(value.encode()).hexdigest()


def _request_hash(
    kind: str, workflow_id: str, store_id: str, data: dict
) -> str:
    """Bind an operation receipt to its action, target, owner and exact payload."""
    return _hash(
        canonical_json(
            {
                "action": kind,
                "workflow_id": workflow_id,
                "store_id": store_id,
                "payload": data,
            }
        )
    )


async def _head(db, scope, actor, workflow_id: str, *, write=False):
    """Always filter ownership explicitly, including identity-map cached targets."""
    authorize(actor, scope)
    row = await db.scalar(
        select(ShopWorkflow).where(
            ShopWorkflow.id == workflow_id,
            ShopWorkflow.store_id.in_(scope.active_store_ids),
        )
    )
    if row is None:
        raise security.SecurityRejected("workflow_not_found", 404)
    authorize(actor, scope, write=write, store_id=row.store_id)
    return row


async def _revision(db, row, revision: int):
    """Read child evidence through both parent and Store predicates."""
    record = await db.scalar(
        select(ShopWorkflowRevision).where(
            ShopWorkflowRevision.workflow_id == row.id,
            ShopWorkflowRevision.store_id == row.store_id,
            ShopWorkflowRevision.revision == revision,
        )
    )
    if record is None:
        raise security.SecurityRejected("workflow_revision_not_found", 404)
    return record


def _snapshot(record) -> dict:
    """Verify stored evidence before deserializing or restoring its definition."""
    if not hmac.compare_digest(
        _hash(record.snapshot_json), record.snapshot_sha256
    ):
        raise security.SecurityRejected("workflow_revision_unreadable", 503)
    return json.loads(record.snapshot_json)


async def _view(db, snapshot, row, scope, actor) -> dict:
    """Keep live validation/readiness separate from immutable saved evidence."""
    definition = Definition.model_validate(snapshot["definition"])
    from services.shop_action_catalog import workflow_report

    validation = await workflow_report(
        db, scope=scope, actor=actor, store_id=row.store_id, definition=definition
    )
    return snapshot | {
        "head_revision": row.revision,
        "validation": validation,
        "runtime_available": False,
        "can_write": security.has_permission(actor.role, "workflows.write")
        and scope.current_store_id == row.store_id
        and scope.current_store.access_level in {"editor", "manager"},
    }


async def read_workflow(db, *, scope, actor, workflow_id: str, revision=None):
    """Read the current draft or one immutable revision inside active Store scope."""
    row = await _head(db, scope, actor, workflow_id)
    if revision is not None and (type(revision) is not int or revision < 1):
        raise security.SecurityRejected("workflow_invalid_request", 422)
    record = await _revision(
        db, row, revision if revision is not None else row.revision
    )
    return await _view(db, _snapshot(record), row, scope, actor)


async def list_workflows(
    db, *, scope, actor, page=1, status="draft", q="", store_id=None
):
    """Page actual Store-owned records; pagination is not a global registration limit."""
    authorize(actor, scope)
    owners = scope.active_store_ids
    if store_id:
        scope.require(store_id)
        owners = (store_id,)
    query = select(ShopWorkflow).where(ShopWorkflow.store_id.in_(owners))
    if status != "all":
        query = query.where(ShopWorkflow.status == status)
    if q:
        query = query.where(ShopWorkflow.name.ilike("%" + q + "%"))
    count = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        (
            await db.execute(
                query.order_by(ShopWorkflow.updated_at.desc(), ShopWorkflow.id)
                .offset((page - 1) * 50)
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "store_id": row.store_id,
                "key": row.key,
                "name": row.name,
                "description": row.description,
                "status": row.status,
                "revision": row.revision,
                "updated_at": security.utc(row.updated_at).isoformat(),
            }
            for row in rows
        ],
        "page": page,
        "total": count,
        "has_more": page * 50 < count,
    }


async def _replay(db, *, store_id, operation_id, digest):
    """Resolve successful retries before comparing an obsolete expected revision."""
    record = await db.scalar(
        select(ShopWorkflowRevision).where(
            ShopWorkflowRevision.store_id == store_id,
            ShopWorkflowRevision.operation_id == operation_id,
        )
    )
    if record and not hmac.compare_digest(record.request_sha256, digest):
        raise security.SecurityRejected("workflow_operation_conflict", 409)
    return record


async def _check_document(db, store_id, definition, layout):
    """Check owner bindings and normalized size without requiring a completed graph."""
    await validate_bindings(db, store_id=store_id, definition=definition)
    if set(layout.positions) - {node.id for node in definition.nodes}:
        raise security.SecurityRejected("workflow_layout_invalid", 422)
    if (
        len(
            canonical_json(
                {
                    "definition": definition.model_dump(mode="json"),
                    "layout": layout.model_dump(mode="json"),
                }
            ).encode()
        )
        > 240 * 1024
    ):
        raise security.SecurityRejected("workflow_too_large", 413)


async def _append(
    db, *, row, actor, operation_id, digest, action, definition, layout
):
    """Append snapshot plus existing audit evidence in the same transaction."""
    snapshot = {
        "id": row.id,
        "store_id": row.store_id,
        "key": row.key,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "schema_version": definition.schema_version,
        "revision": row.revision,
        "operation_id": operation_id,
        "definition": definition.model_dump(mode="json"),
        "layout": layout.model_dump(mode="json"),
        "created_by": row.created_by,
        "updated_by": actor.id,
        "created_at": security.utc(row.created_at).isoformat(),
        "updated_at": security.utc(row.updated_at).isoformat(),
    }
    encoded = canonical_json(snapshot)
    db.add(
        ShopWorkflowRevision(
            id=str(uuid4()),
            workflow_id=row.id,
            store_id=row.store_id,
            revision=row.revision,
            operation_id=operation_id,
            request_sha256=digest,
            snapshot_sha256=_hash(encoded),
            snapshot_json=encoded,
            action=action,
            created_by=actor.id,
            created_at=security.clock(),
        )
    )
    await db.run_sync(
        lambda sync: security.audit(
            sync, actor.id, "workflow." + action, row.id
        )
    )
    await db.flush()
    await db.commit()
    return snapshot


async def _create_draft(
    db,
    *,
    scope,
    actor,
    payload: dict,
    definition=None,
    layout=None,
    action="create",
    source_id=None,
):
    """Idempotently create an unsent draft in the authenticated current Store."""
    authorize(actor, scope, write=True)
    owner, workflow_id = scope.current_store_id, payload["id"]
    digest = _request_hash(
        action,
        workflow_id,
        owner,
        payload | ({"source_id": source_id} if source_id else {}),
    )
    replay = await _replay(
        db, store_id=owner, operation_id=payload["operation_id"], digest=digest
    )
    if replay:
        row = await _head(db, scope, actor, replay.workflow_id)
        return await _view(db, _snapshot(replay), row, scope, actor)
    if definition is None:
        if payload.get("template") == "return_request":
            from services.shop_workflow_templates import (
                return_request_template,
            )

            definition, layout = return_request_template()
        else:
            definition, layout = Definition(), EditorLayout()
    await _check_document(db, owner, definition, layout)
    now = security.clock()
    row = ShopWorkflow(
        id=workflow_id,
        store_id=owner,
        key=payload["key"],
        name=payload["name"].strip(),
        description=payload.get("description", ""),
        status="draft",
        revision=1,
        created_by=actor.id,
        created_at=now,
        updated_at=now,
    )
    if not row.name:
        raise security.SecurityRejected("workflow_invalid_request", 422)
    try:
        db.add(row)
        await db.flush()
        snapshot = await _append(
            db,
            row=row,
            actor=actor,
            operation_id=payload["operation_id"],
            digest=digest,
            action=action,
            definition=definition,
            layout=layout,
        )
    except IntegrityError:
        await db.rollback()
        replay = await _replay(
            db,
            store_id=owner,
            operation_id=payload["operation_id"],
            digest=digest,
        )
        if replay:
            await db.refresh(actor)
            row = await _head(db, scope, actor, replay.workflow_id)
            return await _view(db, _snapshot(replay), row, scope, actor)
        raise security.SecurityRejected("workflow_key_exists", 409) from None
    return await _view(db, snapshot, row, scope, actor)


async def create_draft(db, *, scope, actor, payload: dict):
    """Validate creation inside the shared service, not only in HTTP adapters."""
    authorize(actor, scope, write=True)
    return await _create_draft(
        db,
        scope=scope,
        actor=actor,
        payload=checked_payload(CreateDraft, payload),
    )


async def _mutate(
    db,
    *,
    scope,
    actor,
    workflow_id,
    payload,
    action,
    source_revision=None,
    status=None,
):
    """Compare-and-swap the draft head; every successful operation appends once."""
    row = await _head(db, scope, actor, workflow_id, write=True)
    digest = _request_hash(action, row.id, row.store_id, payload)
    replay = await _replay(
        db,
        store_id=row.store_id,
        operation_id=payload["operation_id"],
        digest=digest,
    )
    if replay:
        return await _view(db, _snapshot(replay), row, scope, actor)
    if payload["expected_revision"] != row.revision:
        raise security.SecurityRejected("workflow_revision_conflict", 409)
    if action in {"save", "archive"} and row.status != "draft":
        raise security.SecurityRejected("workflow_not_draft", 409)
    if action == "delete" and row.status == "deleted":
        raise security.SecurityRejected("workflow_not_draft", 409)
    base = _snapshot(await _revision(db, row, source_revision or row.revision))
    definition = Definition.model_validate(
        payload.get("definition", base["definition"])
    )
    layout = EditorLayout.model_validate(payload.get("layout", base["layout"]))
    if action not in {"archive", "delete"}:
        await _check_document(db, row.store_id, definition, layout)
    name = payload.get("name", base["name"]).strip()
    if not name:
        raise security.SecurityRejected("workflow_invalid_request", 422)
    new_revision = row.revision + 1
    owner = row.store_id
    result = await db.execute(
        update(ShopWorkflow)
        .where(
            ShopWorkflow.id == row.id,
            ShopWorkflow.store_id == scope.current_store_id,
            ShopWorkflow.revision == payload["expected_revision"],
        )
        .values(
            revision=new_revision,
            name=name,
            description=payload.get("description", base["description"]),
            status=status or row.status,
            updated_at=security.clock(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        # A concurrent exact retry may have committed while the CAS waited.
        replay = await _replay(
            db,
            store_id=owner,
            operation_id=payload["operation_id"],
            digest=digest,
        )
        if replay:
            # Rollback expires ORM identities even with expire_on_commit=False.
            await db.refresh(actor)
            authorize(actor, scope)
            await db.refresh(row)
            return await _view(db, _snapshot(replay), row, scope, actor)
        raise security.SecurityRejected("workflow_revision_conflict", 409)
    await db.refresh(row)
    try:
        snapshot = await _append(
            db,
            row=row,
            actor=actor,
            operation_id=payload["operation_id"],
            digest=digest,
            action=action,
            definition=definition,
            layout=layout,
        )
    except IntegrityError:
        await db.rollback()
        replay = await _replay(
            db,
            store_id=owner,
            operation_id=payload["operation_id"],
            digest=digest,
        )
        if replay:
            # Rollback expires ORM identities even with expire_on_commit=False.
            await db.refresh(actor)
            authorize(actor, scope)
            await db.refresh(row)
            return await _view(db, _snapshot(replay), row, scope, actor)
        raise security.SecurityRejected(
            "workflow_operation_conflict", 409
        ) from None
    return await _view(db, snapshot, row, scope, actor)


async def save_draft(db, *, scope, actor, workflow_id, payload):
    """Save typed graph/layout changes with optimistic revision protection."""
    authorize(actor, scope, write=True)
    return await _mutate(
        db,
        scope=scope,
        actor=actor,
        workflow_id=workflow_id,
        payload=checked_payload(SaveDraft, payload),
        action="save",
    )


async def set_status(db, *, scope, actor, workflow_id, payload, status):
    """Soft archive/delete drafts while retaining restorable immutable evidence."""
    authorize(actor, scope, write=True)
    if status not in {"archived", "deleted"}:
        raise security.SecurityRejected("workflow_runtime_unavailable", 409)
    return await _mutate(
        db,
        scope=scope,
        actor=actor,
        workflow_id=workflow_id,
        payload=checked_payload(Operation, payload),
        action="archive" if status == "archived" else "delete",
        status=status,
    )


async def restore_revision(db, *, scope, actor, workflow_id, payload):
    """Copy a prior definition into a new draft revision, never rewrite history."""
    authorize(actor, scope, write=True)
    data = checked_payload(RestoreDraft, payload)
    return await _mutate(
        db,
        scope=scope,
        actor=actor,
        workflow_id=workflow_id,
        payload=data,
        action="restore",
        source_revision=data["revision"],
        status="draft",
    )


async def duplicate_workflow(db, *, scope, actor, workflow_id, payload):
    """Copy an owned immutable snapshot into a distinct same-Store draft identity."""
    source = await _head(db, scope, actor, workflow_id, write=True)
    data = checked_payload(DuplicateDraft, payload)
    snapshot = _snapshot(await _revision(db, source, source.revision))
    return await _create_draft(
        db,
        scope=scope,
        actor=actor,
        payload=data,
        source_id=source.id,
        definition=Definition.model_validate(snapshot["definition"]),
        layout=EditorLayout.model_validate(snapshot["layout"]),
        action="duplicate",
    )


async def list_revisions(db, *, scope, actor, workflow_id, page=1):
    """Page redacted immutable revision metadata through the owning parent."""
    row = await _head(db, scope, actor, workflow_id)
    revisions = (
        (
            await db.execute(
                select(ShopWorkflowRevision)
                .where(
                    ShopWorkflowRevision.workflow_id == row.id,
                    ShopWorkflowRevision.store_id == row.store_id,
                )
                .order_by(ShopWorkflowRevision.revision.desc())
                .offset((page - 1) * 50)
                .limit(51)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "revision": item.revision,
                "operation_id": item.operation_id,
                "action": item.action,
                "created_by": item.created_by,
                "created_at": security.utc(item.created_at).isoformat(),
                "sha256": item.snapshot_sha256,
            }
            for item in revisions[:50]
        ],
        "page": page,
        "has_more": len(revisions) > 50,
        "head_revision": row.revision,
    }


async def operation_result(db, *, scope, actor, workflow_id, operation_id):
    """Reconcile an uncertain write using its immutable scoped receipt."""
    row = await _head(db, scope, actor, workflow_id)
    record = await db.scalar(
        select(ShopWorkflowRevision).where(
            ShopWorkflowRevision.workflow_id == row.id,
            ShopWorkflowRevision.store_id == row.store_id,
            ShopWorkflowRevision.operation_id == operation_id,
        )
    )
    if record is None:
        raise security.SecurityRejected("workflow_operation_not_found", 404)
    return await _view(db, _snapshot(record), row, scope, actor)


async def compare_revisions(db, *, scope, actor, workflow_id, left, right):
    """Compare domain/layout changes rather than opaque renderer snapshots."""
    row = await _head(db, scope, actor, workflow_id)
    a = _snapshot(await _revision(db, row, left))
    b = _snapshot(await _revision(db, row, right))
    result = {"left_revision": left, "right_revision": right}
    for section, key in (
        ("nodes", "id"),
        ("edges", "id"),
        ("variables", "name"),
    ):
        before = {item[key]: item for item in a["definition"][section]}
        after = {item[key]: item for item in b["definition"][section]}
        result[section] = {
            "added": sorted(after.keys() - before.keys()),
            "removed": sorted(before.keys() - after.keys()),
            "changed": sorted(
                item
                for item in before.keys() & after.keys()
                if before[item] != after[item]
            ),
        }
    result["metadata_changed"] = [
        key for key in ("name", "description", "status") if a[key] != b[key]
    ]
    result["layout_changed"] = a["layout"] != b["layout"]
    result["definition_changed"] = a["definition"] != b["definition"]
    return result


async def validate_workflow(db, *, scope, actor, workflow_id, definition=None):
    """Validate an owned saved/unsaved graph without creating a new revision."""
    row = await _head(db, scope, actor, workflow_id)
    if definition is None:
        definition = Definition.model_validate(
            _snapshot(await _revision(db, row, row.revision))["definition"]
        )
    definition = Definition.model_validate(
        checked_payload(ValidateDraft, {"definition": definition})[
            "definition"
        ]
    )
    await validate_bindings(db, store_id=row.store_id, definition=definition)
    from services.shop_action_catalog import workflow_report

    return await workflow_report(
        db, scope=scope, actor=actor, store_id=row.store_id, definition=definition
    )


async def simulate_workflow(db, *, scope, actor, workflow_id, payload):
    """Read an owned revision and replay synthetic inputs without business effects."""
    from models.shop_multibot import ShopBot
    from services.shop_workflow_simulator import SimulationRequest, simulate

    row = await _head(db, scope, actor, workflow_id)
    data = checked_payload(SimulationRequest, payload)
    snapshot = _snapshot(await _revision(db, row, data["revision"]))
    definition = Definition.model_validate(snapshot["definition"])
    await validate_bindings(db, store_id=row.store_id, definition=definition)
    bot = await db.scalar(
        select(ShopBot).where(
            ShopBot.id == data["bot_id"],
            ShopBot.store_id == row.store_id,
            ShopBot.platform == data["platform"],
            ShopBot.status != "disabled",
        )
    )
    if (
        bot is None
        or data["platform"] not in definition.target_platforms
        or definition.assignment.mode == "selected"
        and bot.id not in definition.assignment.bot_ids
    ):
        raise security.SecurityRejected("workflow_bot_not_available", 422)
    owner = next(
        item for item in scope.allowed_stores if item.id == row.store_id
    )
    context = data["context"] | {
        "store_name": owner.name,
        "bot_name": bot.name,
    }
    return simulate(
        definition,
        platform=data["platform"],
        context=context,
        events=data["events"],
    ) | {
        "workflow_id": row.id,
        "revision": data["revision"],
        "head_revision": row.revision,
        "bot_id": bot.id,
        "platform": bot.platform,
    }
