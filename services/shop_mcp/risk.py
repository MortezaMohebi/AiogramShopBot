"""One conservative approval policy across every designer mutation path."""

from services.shop_actions.definitions import definitions


def mutation_risk(before: dict, after: dict, *, kind: str = "save") -> str:
    """Review semantic edits involving any mutating or unknown typed Action.

    Variables and routing can alter Action input indirectly, so checking only
    changed Action nodes would permit an approval bypass. Pure metadata and
    geometry edits remain reversible low-risk draft work.
    """
    if kind == "archive":
        return "destructive"
    old, new = before.get("definition"), after.get("definition")
    if kind not in {"create", "duplicate"} and old == new:
        return "low"
    registry = {
        (item.descriptor.key, item.descriptor.version): item.descriptor
        for item in definitions()
    }
    for definition in (old, new):
        for node in (definition or {}).get("nodes", []):
            if node["type"] != "action":
                continue
            config = node["config"]
            descriptor = registry.get(
                (
                    config.get("action_key"),
                    config.get("action_version"),
                )
            )
            if descriptor is None or descriptor.side_effect != "read_only":
                return "high"
    return "low"
