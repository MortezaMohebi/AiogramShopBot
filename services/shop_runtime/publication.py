"""Reviewed publication and entry activation; drafts never execute implicitly."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from models.shop_multibot import ShopBot, ShopStore
from models.shop_workflow import ShopWorkflow, ShopWorkflowRevision
from models.shop_workflow_runtime import (
    PublishedWorkflow,
    PublicationPreview,
    RuntimeBinding,
    RuntimeAudit,
)
from services import shop_admin_security as security
from services.shop_runtime.contracts import (
    BindingSpec,
    RuntimeRejected,
    publication_findings,
)
from services.shop_workflow_schema import Definition, canonical_json
from services.shop_workflow_bindings import validate_bindings
from services.shop_action_catalog import workflow_report
from services.shop_actions.definitions import definition as action_definition


def digest(value) -> str:
    """Hash a bounded canonical request without storing secret authorization tokens."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def require_manager(actor, scope):
    """Publication is separate from draft editing and requires Store management."""
    if actor is None or actor.id != scope.staff_id or not actor.is_active:
        raise RuntimeRejected("session_expired", 401)
    security.require_permission(actor.role, "workflows.publish")
    scope.require(scope.current_store_id, manage=True)


async def lock_routes(db, store_id):
    """Fence publication/retirement, including missing keys, without blocking FKs.

    Administration is infrequent. One Store mutex avoids locking an unbounded
    routing key set in different orders; workers only need parent KEY SHARE.
    """
    await db.scalar(
        select(ShopStore.id)
        .where(ShopStore.id == store_id)
        .with_for_update(key_share=True)
    )


async def _source(db, store_id, workflow_id, revision):
    """Load an owned immutable revision; archive/deletion prevents new activation."""
    head = await db.scalar(
        select(ShopWorkflow)
        .where(
            ShopWorkflow.id == workflow_id,
            ShopWorkflow.store_id == store_id,
        )
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if head is None or head.status != "draft":
        raise RuntimeRejected("runtime_workflow_unavailable", 404)
    row = await db.scalar(
        select(ShopWorkflowRevision).where(
            ShopWorkflowRevision.workflow_id == workflow_id,
            ShopWorkflowRevision.store_id == store_id,
            ShopWorkflowRevision.revision == revision,
        )
    )
    if row is None:
        raise RuntimeRejected("runtime_revision_unavailable", 404)
    return head, Definition.model_validate(json.loads(row.snapshot_json)["definition"])


async def binding_state(db, bot_ids):
    """Fingerprint all relevant entry pointers so a preview cannot replace new edits."""
    rows = (
        await db.scalars(
            select(RuntimeBinding)
            .where(
                RuntimeBinding.bot_id.in_(bot_ids),
            )
            .order_by(RuntimeBinding.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    return [
        {
            "id": x.id,
            "bot_id": x.bot_id,
            "node_id": x.node_id,
            "version": x.version,
            "publication_id": x.publication_id,
            "kind": x.kind,
            "key": x.key,
            "enabled": x.enabled,
        }
        for x in rows
    ]


def confirmation_findings(definition):
    """Require customer review on every path before a confirmation-bound mutation."""
    nodes = {n.id: n for n in definition.nodes}
    starts = [e.node_id for e in definition.entry_points] or [
        n.id for n in nodes.values() if n.type == "start"
    ]
    found = []
    for platform in definition.target_platforms:
        pending = [(start, False) for start in starts]
        seen = set()
        while pending:
            node_id, confirmed = pending.pop()
            if (node_id, confirmed) in seen or node_id not in nodes:
                continue
            seen.add((node_id, confirmed))
            node = nodes[node_id]
            config = node.config | node.platform_overrides.get(platform, {})
            if node.type.startswith("ask_") or node.type in {
                "wait_for_input",
                "set_variable",
            }:
                confirmed = False
            if node.type == "action":
                spec = action_definition(config["action_key"], config["action_version"])
                if (
                    spec
                    and spec.descriptor.confirmation
                    in {"customer_confirmation", "both"}
                    and not confirmed
                ):
                    found.append(
                        {
                            "code": "runtime_confirmation_required",
                            "node_id": node.id,
                            "platform": platform,
                            "severity": "error",
                        }
                    )
                confirmed = False
            targets = {
                e.port: e.target for e in definition.edges if e.source == node.id
            }
            if node.type == "go_to_step":
                targets = {"next": config["target"]}
            elif node.type == "show_buttons":
                # Hidden conditions may change at runtime; consider every offerable
                # callback for this platform and the independent timeout transition.
                targets = {
                    **({"timeout": targets["timeout"]} if "timeout" in targets else {}),
                    **{
                        b["key"]: b.get("target") or targets.get(b["key"])
                        for b in config["buttons"]
                        if b["type"] == "callback" and platform in b["platforms"]
                    },
                }
            for port, target in targets.items():
                pending.append(
                    (target, port == "confirm" if node.type == "confirm" else confirmed)
                )
    return found


def presentation_findings(definition, *, media_kinds=None):
    """Reject editable presentation that the live Runtime renderer cannot send.

    Visibility conditions can hide buttons at runtime, so publication checks the
    largest possible keyboard for each platform. Media ownership is independently
    enforced before this compatibility check.
    """
    from services.shop_platform_capabilities import CAPABILITIES
    from services.shop_runtime.adapters import _markup

    findings = []
    for node in definition.nodes:
        for platform in definition.target_platforms:
            config = node.config | node.platform_overrides.get(platform, {})
            buttons = []
            if node.type == "show_buttons":
                buttons = [b for b in config["buttons"] if platform in b["platforms"]]
            elif node.type == "ask_choice":
                buttons = config["choices"]
            elif node.type == "confirm":
                buttons = [
                    {"label": config[key]} for key in ("confirm_label", "cancel_label")
                ]
            code = None
            capabilities = CAPABILITIES[platform]
            reserved = {"back", "cancel", "skip", "main_menu", "confirm"}
            if node.type == "show_buttons" and any(
                b["type"] in {"action", "request_contact"}
                or (b["type"] == "callback" and b["key"] in reserved)
                or (
                    b["type"] in {"back", "cancel", "main_menu"}
                    and any(b.get(key) for key in ("target", "action", "url"))
                )
                or (
                    config["keyboard"] == "reply"
                    and (b["type"] != "callback" or b["label"].startswith("/"))
                )
                for b in buttons
            ):
                code = "runtime_button_semantics_unsupported"
            if node.type == "ask_choice" and any(b["key"] in reserved for b in buttons):
                code = "runtime_button_semantics_unsupported"
            if node.type == "action":
                ports = {
                    e.port: e.target for e in definition.edges if e.source == node.id
                }
                if any(
                    ports.get(key) != ports.get("error")
                    for key in ("retry", "pending_approval")
                ):
                    code = "runtime_action_wait_port_unsupported"
            if any(
                len(b["label"]) > capabilities["runtime_keyboard_label_characters"]
                for b in buttons
            ):
                code = "runtime_keyboard_label_limit"
            if any(
                count > capabilities["runtime_keyboard_row_buttons"]
                for count in Counter(b.get("row", 0) for b in buttons).values()
            ):
                code = "runtime_keyboard_row_limit"
            if code is None and node.type in {"show_buttons", "ask_choice", "confirm"}:
                # Reuse the adapter's pure preparation check. These inert placeholders
                # are never persisted as callback capabilities or sent to a provider.
                rendered = [
                    {
                        "label": b["label"],
                        "row": b.get("row", 0),
                        **(
                            {"url": b["url"]}
                            if b.get("type") == "url"
                            else {"callback_data": "wf:publication-validation"}
                        ),
                    }
                    for b in buttons
                ]
                try:
                    _markup(
                        {
                            "keyboard": config.get("keyboard", "inline"),
                            "buttons": rendered,
                        }
                    )
                except RuntimeRejected as error:
                    code = error.code
            if node.type == "send_media_group" and media_kinds is not None:
                kinds = {media_kinds.get(key) for key in config["media_ids"]}
                if not kinds.issubset({"photo", "video", "document"}):
                    code = "runtime_media_kind_invalid"
                elif "document" in kinds and kinds != {"document"}:
                    code = "runtime_album_media_incompatible"
            if (
                node.type == "send_media_group"
                and not capabilities["runtime_media_group"]
            ):
                code = "runtime_media_group_unavailable"
            if code:
                findings.append(
                    {
                        "code": code,
                        "node_id": node.id,
                        "platform": platform,
                        "severity": "error",
                    }
                )
    return findings


async def readiness(db, *, actor, scope, workflow_id, revision, bindings):
    """Revalidate graph, exact Actions, Store/Bot/media and entry conflicts live."""
    head, definition = await _source(db, scope.current_store_id, workflow_id, revision)
    await validate_bindings(db, store_id=head.store_id, definition=definition)
    report = await workflow_report(
        db, scope=scope, actor=actor, store_id=head.store_id, definition=definition
    )
    findings = [x for x in report["issues"] if x.get("blocks_activation", True)]
    findings = [
        x
        for x in findings
        if not (
            x["code"] == "adapter_action_unavailable"
            and any(
                n.id == x.get("node_id") and n.type == "send_media_group"
                for n in definition.nodes
            )
        )
    ]
    findings += publication_findings(definition) + confirmation_findings(definition)
    album_ids = {
        key
        for node in definition.nodes
        if node.type == "send_media_group"
        for platform in definition.target_platforms
        for key in (node.config | node.platform_overrides.get(platform, {}))[
            "media_ids"
        ]
    }
    media_kinds = {}
    if album_ids:
        from models.shop_content import Product, ProductMedia

        media_kinds = dict(
            (
                await db.execute(
                    select(ProductMedia.id, ProductMedia.kind)
                    .join(Product, Product.id == ProductMedia.product_id)
                    .where(
                        Product.store_id == head.store_id,
                        ProductMedia.id.in_(album_ids),
                    )
                )
            ).all()
        )
    findings += presentation_findings(definition, media_kinds=media_kinds)
    nodes = {x.id: x for x in definition.nodes}
    if not bindings:
        findings.append({"code": "runtime_entry_required", "severity": "error"})
    seen = set()
    declared = {(e.kind, e.key, e.node_id) for e in definition.entry_points}
    # Lock the reviewed Bot metadata in stable order; concurrent child FK
    # inserts (inbox, identities, receipts) only need compatible KEY SHARE.
    bots = {
        bot.id: bot
        for bot in (
            await db.scalars(
                select(ShopBot)
                .where(
                    ShopBot.id.in_({b.bot_id for b in bindings}),
                    ShopBot.store_id == head.store_id,
                )
                .order_by(ShopBot.id)
                .with_for_update(key_share=True)
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    for item in bindings:
        bot = bots.get(item.bot_id)
        if (
            bot is None
            or bot.store_id != head.store_id
            or bot.platform not in definition.target_platforms
            or bot.status not in {"active", "legacy"}
            or (
                definition.assignment.mode == "selected"
                and bot.id not in definition.assignment.bot_ids
            )
        ):
            raise RuntimeRejected("runtime_bot_unavailable", 422)
        if item.kind in {"admin_test", "legacy_bridge"} and item.node_id not in {
            e.node_id for e in definition.entry_points
        }:
            raise RuntimeRejected("runtime_entry_not_declared", 422)
        if item.node_id not in nodes:
            raise RuntimeRejected("runtime_entry_node_missing", 422)
        if (
            item.kind not in {"legacy_bridge", "admin_test"}
            and (item.kind, item.key, item.node_id) not in declared
        ):
            raise RuntimeRejected("runtime_entry_not_declared", 422)
        key = (item.bot_id, item.kind, item.key)
        if key in seen:
            raise RuntimeRejected("runtime_entry_conflict")
        seen.add(key)
        current = await db.scalar(
            select(RuntimeBinding).where(
                RuntimeBinding.bot_id == item.bot_id,
                RuntimeBinding.kind == item.kind,
                RuntimeBinding.key == item.key,
            )
        )
        if current and current.workflow_id != workflow_id:
            raise RuntimeRejected("runtime_entry_conflict")
    risks = []
    dependencies = []
    for node in definition.nodes:
        if node.type == "action":
            spec = action_definition(
                node.config["action_key"], node.config["action_version"]
            )
            if spec:
                dependencies.append(
                    {
                        "node_id": node.id,
                        "key": spec.descriptor.key,
                        "version": spec.descriptor.version,
                        "confirmation": spec.descriptor.confirmation,
                        "side_effect": spec.descriptor.side_effect,
                    }
                )
                if spec.descriptor.side_effect not in {"none", "read_only"}:
                    risks.append(node.id)
    return definition, {
        "ready": not findings,
        "issues": findings,
        "dependencies": dependencies,
        "mutating_nodes": risks,
        "platforms": definition.target_platforms,
    }


async def preview(db, *, actor, scope, workflow_id, revision, bindings):
    """Create a reviewable, session-bound preview without activating any Bot."""
    require_manager(actor, scope)
    await lock_routes(db, scope.current_store_id)
    specs = [BindingSpec.model_validate(x) for x in bindings]
    definition, report = await readiness(
        db,
        actor=actor,
        scope=scope,
        workflow_id=workflow_id,
        revision=revision,
        bindings=specs,
    )
    pointers = await binding_state(db, [x.bot_id for x in specs])
    selected = {(s.bot_id, s.kind, s.key) for s in specs}
    active = {
        (x["bot_id"], x["kind"], x["key"]): x["publication_id"]
        for x in pointers
        if (x["bot_id"], x["kind"], x["key"]) in selected
    }
    # Immutable metadata suffices: never put whole definitions into preview receipts.
    versions = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    PublishedWorkflow.id,
                    PublishedWorkflow.revision,
                    PublishedWorkflow.digest,
                ).where(
                    PublishedWorkflow.store_id == scope.current_store_id,
                    PublishedWorkflow.workflow_id == workflow_id,
                    PublishedWorkflow.id.in_(set(active.values())),
                )
            )
        ).all()
    }
    next_digest = digest(definition)
    comparisons = []
    for spec in specs:
        previous_id = active.get((spec.bot_id, spec.kind, spec.key))
        previous = versions.get(previous_id)
        if previous_id and previous is None:
            raise RuntimeRejected("runtime_entry_conflict")
        comparisons.append(
            {
                "bot_id": spec.bot_id,
                "kind": spec.kind,
                "key": spec.key,
                "previous_publication_id": previous_id,
                "previous_revision": previous.revision if previous else None,
                "definition_changed": previous is None
                or previous.digest != next_digest,
            }
        )
    baselines = {item["previous_revision"] for item in comparisons}
    report["diff"] = {
        "binding_comparisons": comparisons,
        "previous_revision": next(iter(baselines)) if len(baselines) == 1 else None,
        "next_revision": revision,
        "definition_changed": any(item["definition_changed"] for item in comparisons),
        "previous_bindings": pointers,
        "next_bindings": [x.model_dump() for x in specs],
        "unchanged_bindings": [
            x for x in pointers if (x["bot_id"], x["kind"], x["key"]) not in selected
        ],
        "retains_unselected_bindings": True,
    }
    request = {
        "definition_digest": digest(definition),
        "bindings": [x.model_dump() for x in specs],
        "pointers": pointers,
    }
    row = PublicationPreview(
        id=str(uuid4()),
        store_id=scope.current_store_id,
        workflow_id=workflow_id,
        revision=revision,
        staff_id=actor.id,
        session_id=scope.session_id,
        digest=digest(request),
        request=request,
        report=report,
        expires_at=security.clock() + timedelta(minutes=5),
    )
    db.add(row)
    await db.commit()
    return {
        "preview_id": row.id,
        "expires_at": security.utc(row.expires_at).isoformat(),
        **report,
    }


async def activate(db, *, actor, scope, preview_id, approved):
    """Consume exactly the reviewed request atomically with all activation pointers."""
    require_manager(actor, scope)
    if approved is not True:
        raise RuntimeRejected("runtime_approval_required", 422)
    row = await db.scalar(
        select(PublicationPreview)
        .where(
            PublicationPreview.id == preview_id,
            PublicationPreview.store_id == scope.current_store_id,
            PublicationPreview.staff_id == actor.id,
            PublicationPreview.session_id == scope.session_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise RuntimeRejected("runtime_preview_unavailable", 404)
    if row.publication_id:
        return {
            "publication_id": row.publication_id,
            "preview_id": row.id,
            "replayed": True,
        }
    if security.utc(row.expires_at) <= security.clock():
        raise RuntimeRejected("runtime_preview_expired")
    await lock_routes(db, row.store_id)
    specs = [BindingSpec.model_validate(x) for x in row.request["bindings"]]
    definition, report = await readiness(
        db,
        actor=actor,
        scope=scope,
        workflow_id=row.workflow_id,
        revision=row.revision,
        bindings=specs,
    )
    pointers = await binding_state(db, [x.bot_id for x in specs])
    if not report["ready"]:
        raise RuntimeRejected("runtime_publication_not_ready", 422)
    if (
        digest(definition) != row.request["definition_digest"]
        or pointers != row.request["pointers"]
    ):
        raise RuntimeRejected("runtime_preview_conflict")
    published = await db.scalar(
        select(PublishedWorkflow).where(
            PublishedWorkflow.workflow_id == row.workflow_id,
            PublishedWorkflow.revision == row.revision,
            PublishedWorkflow.store_id == row.store_id,
        )
    )
    if published is None:
        published = PublishedWorkflow(
            id=str(uuid4()),
            store_id=row.store_id,
            workflow_id=row.workflow_id,
            revision=row.revision,
            definition=definition.model_dump(mode="json"),
            digest=digest(definition),
            published_by=actor.id,
        )
        db.add(published)
        await db.flush()
    if await db.scalar(
        select(RuntimeAudit.id).where(
            RuntimeAudit.action == "retire", RuntimeAudit.target_id == published.id
        )
    ):
        raise RuntimeRejected("runtime_publication_retired")
    for spec in specs:
        binding = await db.scalar(
            select(RuntimeBinding)
            .where(
                RuntimeBinding.bot_id == spec.bot_id,
                RuntimeBinding.kind == spec.kind,
                RuntimeBinding.key == spec.key,
            )
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if binding is None:
            binding = RuntimeBinding(
                id=str(uuid4()),
                store_id=row.store_id,
                workflow_id=row.workflow_id,
                publication_id=published.id,
                **spec.model_dump(exclude={"version_policy"}),
            )
            db.add(binding)
        else:
            if (
                binding.workflow_id != row.workflow_id
                or binding.store_id != row.store_id
            ):
                raise RuntimeRejected("runtime_entry_conflict")
            binding.publication_id = published.id
            binding.version += 1
            for key, value in spec.model_dump(
                exclude={"bot_id", "kind", "key", "version_policy"}
            ).items():
                setattr(binding, key, value)
    row.publication_id = published.id
    db.add(
        RuntimeAudit(
            store_id=row.store_id,
            staff_id=actor.id,
            action="activate",
            target_id=published.id,
            summary={"revision": row.revision, "preview_id": row.id},
        )
    )
    await db.commit()
    return {
        "publication_id": published.id,
        "preview_id": row.id,
        "revision": published.revision,
        "replayed": False,
    }
