"""Publication rejects presentation that the receipt-bearing Runtime adapters cannot send."""

import pytest

from services.shop_runtime.publication import presentation_findings
from services.shop_workflow_schema import Definition
from tests.test_workflow_schema import document
from tests.test_workflow_api import studio
from tests.test_campaign_admin_store_scope import campaign_app
from tests.test_runtime_api import runtime_manager


def menu(buttons):
    """Use the real editable schema, whose limits intentionally exceed live adapter limits."""
    data = document()
    data["nodes"].insert(
        1,
        {
            "id": "menu",
            "type": "show_buttons",
            "config": {
                "text": "Choose",
                "buttons": buttons,
            },
        },
    )
    return Definition.model_validate(data)


@pytest.mark.parametrize(
    "config",
    [
        [{"key": "done", "label": "a" * 65, "target": "end"}],
        [
            {"key": f"choice{i}", "label": str(i), "row": 0, "target": "end"}
            for i in range(9)
        ],
    ],
)
def test_live_keyboard_limits_block_publication(config):
    """A valid draft cannot publish a keyboard that definitely fails before sending."""
    findings = presentation_findings(menu(config))
    assert {item["platform"] for item in findings} == {"telegram", "bale"}
    assert all(
        item["severity"] == "error" and item["node_id"] == "menu" for item in findings
    )


def test_keyboard_counts_are_platform_specific():
    """Separate platform buttons do not consume the other platform's row budget."""
    buttons = [
        {"key": f"t{i}", "label": str(i), "platforms": ["telegram"], "target": "end"}
        for i in range(8)
    ]
    buttons += [
        {"key": f"b{i}", "label": str(i), "platforms": ["bale"], "target": "end"}
        for i in range(8)
    ]
    assert presentation_findings(menu(buttons)) == []


def test_duplicate_reply_labels_and_empty_confirmation_fail_readiness():
    """Publication uses the same pure keyboard validator as the provider adapter."""
    data = menu(
        [
            {"key": "a", "label": "Same", "target": "end"},
            {"key": "b", "label": "Same", "target": "end"},
        ]
    ).model_dump(mode="json")
    data["nodes"][1]["config"]["keyboard"] = "reply"
    assert any(
        item["code"] == "runtime_reply_button_ambiguous"
        for item in presentation_findings(Definition.model_validate(data))
    )
    data = document()
    data["nodes"].insert(
        1,
        {
            "id": "review",
            "type": "confirm",
            "config": {
                "prompt": "Review",
                "confirm_label": "",
                "cancel_label": "Cancel",
            },
        },
    )
    assert any(
        item["code"] == "runtime_buttons_invalid"
        for item in presentation_findings(Definition.model_validate(data))
    )


def test_mixed_document_album_is_rejected_before_activation():
    """Store-owned media can still be incompatible with a single provider album call."""
    data = document()
    data["nodes"].insert(
        1, {"id": "album", "type": "send_media_group", "config": {"media_ids": [1, 2]}}
    )
    definition = Definition.model_validate(data)
    assert any(
        item["code"] == "runtime_album_media_incompatible"
        for item in presentation_findings(
            definition, media_kinds={1: "photo", 2: "document"}
        )
    )
    assert presentation_findings(definition, media_kinds={1: "photo", 2: "video"}) == []
    assert any(
        item["code"] == "runtime_media_kind_invalid"
        for item in presentation_findings(
            definition, media_kinds={1: "audio", 2: "audio"}
        )
    )


@pytest.mark.asyncio
async def test_publication_preview_reports_live_keyboard_rejection(runtime_manager):
    """An editable graph stays saved while its incompatible live publication is blocked."""
    from models.shop_staff import ShopStaff
    from tests.test_campaign_admin_store_scope import BOT_A
    from tests.test_workflow_api import create, update

    app = runtime_manager
    created = await create(app)
    definition = menu(
        [{"key": f"c{i}", "label": str(i), "target": "end"} for i in range(9)]
    ).model_dump(mode="json")
    definition["edges"] = [{"id": "to_menu", "source": "s", "target": "menu"}]
    saved = await app.request(
        "PATCH",
        "/workflows/" + created["id"],
        payload=update(created, definition=definition),
    )
    assert saved.status_code == 200, saved.text
    app.db.get(ShopStaff, 7).role = "superadmin"
    app.db.commit()
    result = await app.request(
        "POST",
        "/workflow-runtime/publications/preview",
        payload={
            "workflow_id": created["id"],
            "revision": 2,
            "bindings": [
                {"bot_id": BOT_A, "kind": "start", "key": "default", "node_id": "s"}
            ],
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["ready"] is False
    assert any(
        item["code"] == "runtime_keyboard_row_limit" for item in result.json()["issues"]
    )
