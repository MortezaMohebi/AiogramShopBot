import type {
  DraftDocument,
  WorkflowRecord,
  DomainNode,
  NodeSpec,
  WorkflowButton,
  Choice,
} from "./types";
/** Stable key ordering supports dirty checks without serializing renderer state. */
export function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value)
    .sort()
    .map(
      (k) =>
        `${JSON.stringify(k)}:${canonical((value as Record<string, unknown>)[k])}`,
    )
    .join(",")}}`;
}
export function documentOf(record: DraftDocument): DraftDocument {
  return structuredClone({
    name: record.name,
    description: record.description,
    definition: record.definition,
    layout: record.layout,
  });
}
export interface EditorState {
  document: DraftDocument;
  past: DraftDocument[];
  future: DraftDocument[];
}
export type EditorAction =
  | { type: "edit"; document: DraftDocument; coalesce?: boolean }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "remove"; ids: string[] }
  | { type: "replace"; document: DraftDocument };
export function initialEditor(document: DraftDocument): EditorState {
  return { document: documentOf(document), past: [], future: [] };
}
export function editorReducer(
  state: EditorState,
  action: EditorAction,
): EditorState {
  if (action.type === "undo") {
    const previous = state.past.at(-1);
    return previous
      ? {
          document: previous,
          past: state.past.slice(0, -1),
          future: [state.document, ...state.future],
        }
      : state;
  }
  if (action.type === "redo") {
    const next = state.future[0];
    return next
      ? {
          document: next,
          past: [...state.past, state.document].slice(-100),
          future: state.future.slice(1),
        }
      : state;
  }
  const document =
    action.type === "remove"
      ? removeNodes(state.document, action.ids)
      : documentOf(action.document);
  if (canonical(document) === canonical(state.document)) return state;
  return {
    document,
    past:
      action.type === "replace"
        ? state.past
        : action.type === "edit" && action.coalesce
          ? state.past
          : [...state.past, state.document].slice(-100),
    future: [],
  };
}
/** One outgoing edge per semantic port; button targets and graph cannot diverge. */
export function connect(
  document: DraftDocument,
  source: string,
  target: string,
  port: string,
  id: string,
): DraftDocument {
  const d = documentOf(document);
  if (
    source === target &&
    !d.definition.nodes.find((n) => n.id === source)?.max_visits
  )
    return d;
  if (
    !d.definition.nodes.some((n) => n.id === source) ||
    !d.definition.nodes.some((n) => n.id === target)
  )
    return d;
  d.definition.edges = d.definition.edges.filter(
    (e) => !(e.source === source && e.port === port),
  );
  d.definition.edges.push({ id, source, target, port });
  const n = d.definition.nodes.find((n) => n.id === source)!;
  if (n.type === "show_buttons")
    n.config.buttons = (n.config.buttons as WorkflowButton[]).map((b) =>
      b.key === port ? { ...b, target } : b,
    );
  if (n.type === "go_to_step") n.config.target = target;
  return d;
}
export function disconnect(
  document: DraftDocument,
  edgeIds: string[],
): DraftDocument {
  const d = documentOf(document);
  const removed = d.definition.edges.filter((e) => edgeIds.includes(e.id));
  d.definition.edges = d.definition.edges.filter(
    (e) => !edgeIds.includes(e.id),
  );
  for (const e of removed) {
    const n = d.definition.nodes.find((n) => n.id === e.source);
    if (n?.type === "show_buttons")
      n.config.buttons = (n.config.buttons as WorkflowButton[]).map((b) =>
        b.key === e.port ? { ...b, target: "" } : b,
      );
    if (n?.type === "go_to_step") n.config.target = "";
  }
  return d;
}
export function removeNodes(
  document: DraftDocument,
  ids: string[],
): DraftDocument {
  const d = documentOf(document);
  d.definition.nodes = d.definition.nodes.filter((n) => !ids.includes(n.id));
  d.definition.edges = d.definition.edges.filter(
    (e) => !ids.includes(e.source) && !ids.includes(e.target),
  );
  d.definition.entry_points = d.definition.entry_points.filter(
    (e) => !ids.includes(e.node_id),
  );
  for (const id of ids) delete d.layout.positions[id];
  for (const n of d.definition.nodes) {
    if (n.type === "go_to_step" && ids.includes(String(n.config.target)))
      n.config.target = "";
    if (n.type === "show_buttons")
      n.config.buttons = (n.config.buttons as WorkflowButton[]).map((b) =>
        ids.includes(b.target) ? { ...b, target: "" } : b,
      );
  }
  return d;
}
/** Copies only selected domain nodes and internal references, with fresh stable IDs. */
export function cloneSelection(
  document: DraftDocument,
  ids: string[],
  prefix: string,
): DraftDocument {
  const d = documentOf(document),
    mapping = new Map(ids.map((id, i) => [id, `${prefix}_${i}`]));
  if (d.definition.nodes.length + ids.length > 200) return d;
  const copies = d.definition.nodes
    .filter((n) => mapping.has(n.id))
    .map((n) => {
      const copy = structuredClone(n);
      copy.id = mapping.get(n.id)!;
      copy.label = `${n.label} (کپی)`;
      if (copy.type === "go_to_step")
        copy.config.target = mapping.get(String(copy.config.target)) ?? "";
      if (copy.type === "show_buttons")
        copy.config.buttons = (copy.config.buttons as WorkflowButton[]).map(
          (b) => ({ ...b, target: mapping.get(b.target) ?? "" }),
        );
      const p = d.layout.positions[n.id] ?? { x: 0, y: 0 };
      d.layout.positions[copy.id] = { x: p.x + 50, y: p.y + 70 };
      return copy;
    });
  const edges = d.definition.edges
    .filter((e) => mapping.has(e.source) && mapping.has(e.target))
    .map((e, i) => ({
      ...e,
      id: `${prefix}_edge_${i}`,
      source: mapping.get(e.source)!,
      target: mapping.get(e.target)!,
    }));
  d.definition.nodes.push(...copies);
  d.definition.edges.push(...edges);
  return d;
}
/** Breadth levels stay bounded even for cycles and disconnected draft fragments. */
export function autoLayout(document: DraftDocument): DraftDocument {
  const d = documentOf(document);
  const levels = new Map<string, number>();
  const first = d.definition.nodes
    .filter((n) => n.type === "start")
    .map((n) => n.id);
  const queue = first.map((id) => ({ id, level: 0 }));
  while (queue.length) {
    const { id, level } = queue.shift()!;
    if (levels.has(id)) continue;
    levels.set(id, level);
    for (const e of d.definition.edges.filter((e) => e.source === id))
      queue.push({ id: e.target, level: level + 1 });
  }
  for (const n of d.definition.nodes)
    if (!levels.has(n.id)) levels.set(n.id, 0);
  const rows = new Map<number, number>();
  d.layout.positions = {};
  for (const n of d.definition.nodes) {
    const col = levels.get(n.id)!;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    d.layout.positions[n.id] = { x: col * 300, y: row * 160 };
  }
  return d;
}
export function nodePorts(
  node: DomainNode,
  spec: NodeSpec | undefined,
): string[] {
  if (node.type === "show_buttons")
    return ((node.config.buttons as WorkflowButton[]) ?? [])
      .filter((b) => b.type === "callback" || b.type === "action")
      .map((b) => b.key);
  if (node.type === "switch")
    return [
      ...((node.config.cases as Choice[]) ?? []).map((c) => c.key),
      "default",
    ];
  return spec?.ports ?? [];
}
/** A response confirms only the submitted snapshot, never newer local typing. */
export function mergeSave(
  current: DraftDocument,
  submitted: DraftDocument,
  record: WorkflowRecord,
) {
  const saved = documentOf(record),
    unchanged = canonical(current) === canonical(submitted);
  const document = unchanged ? saved : current;
  return {
    document,
    revision: record.revision,
    concurrent: record.head_revision !== record.revision,
    dirty: canonical(document) !== canonical(saved),
    savedFingerprint: canonical(saved),
  };
}
