import assert from "node:assert/strict";
import { test } from "node:test";
import {
  editorReducer,
  initialEditor,
  connect,
  cloneSelection,
  autoLayout,
  canonical,
  mergeSave,
} from "../lib/workflows/state.ts";
import type { DraftDocument, WorkflowRecord } from "../lib/workflows/types.ts";
const doc = (): DraftDocument => ({
  name: "آزمایش",
  description: "",
  definition: {
    schema_version: 1,
    target_platforms: ["telegram", "bale"],
    assignment: { mode: "all_eligible", bot_ids: [] },
    entry_points: [
      { kind: "start", key: "main", node_id: "start", command: "" },
    ],
    nodes: [
      {
        id: "start",
        type: "start",
        label: "شروع",
        config: {},
        platform_overrides: {},
        max_visits: null,
      },
      {
        id: "buttons",
        type: "show_buttons",
        label: "منو",
        config: {
          text: "انتخاب",
          keyboard: "inline",
          buttons: [
            {
              key: "ok",
              label: "ادامه",
              type: "callback",
              row: 0,
              target: "",
              url: "",
              action: "",
              visible_when: null,
              platforms: ["telegram", "bale"],
            },
          ],
        },
        platform_overrides: {},
        max_visits: null,
      },
      {
        id: "end",
        type: "end",
        label: "پایان",
        config: { message: "" },
        platform_overrides: {},
        max_visits: null,
      },
    ],
    edges: [],
    variables: [],
    error_policy: { max_steps: 100, on_error: "stop", message: "خطا" },
    timeout_policy: { seconds: 300, outcome: "cancel" },
  },
  layout: {
    positions: {
      start: { x: 0, y: 0 },
      buttons: { x: 240, y: 0 },
      end: { x: 480, y: 0 },
    },
    viewport: { x: 0, y: 0, zoom: 1 },
  },
});
test("connection replaces an outgoing port and updates canonical button target", () => {
  let d = connect(doc(), "buttons", "end", "ok", "edge1");
  d = connect(d, "buttons", "start", "ok", "edge2");
  assert.equal(d.definition.edges.length, 1);
  assert.equal(d.definition.edges[0].target, "start");
  assert.equal(
    (d.definition.nodes[1].config.buttons as { target: string }[])[0].target,
    "start",
  );
});
test("undo and redo preserve typed values and reject redo after a new edit", () => {
  let s = initialEditor(doc());
  s = editorReducer(s, {
    type: "edit",
    document: { ...s.document, name: "دوم" },
  });
  s = editorReducer(s, { type: "undo" });
  assert.equal(s.document.name, "آزمایش");
  s = editorReducer(s, { type: "redo" });
  assert.equal(s.document.name, "دوم");
  s = editorReducer(s, { type: "undo" });
  s = editorReducer(s, {
    type: "edit",
    document: { ...s.document, name: "سوم" },
  });
  assert.equal(s.future.length, 0);
});
test("delete removes edges, layout, entry points and button targets without mutating source", () => {
  const original = connect(doc(), "buttons", "end", "ok", "edge1");
  const s = editorReducer(initialEditor(original), {
    type: "remove",
    ids: ["end"],
  });
  assert.equal(s.document.definition.edges.length, 0);
  assert.equal(
    (s.document.definition.nodes[1].config.buttons as { target: string }[])[0]
      .target,
    "",
  );
  assert.equal(s.document.layout.positions.end, undefined);
  assert.equal(original.definition.nodes.length, 3);
});
test("copy remaps internal node IDs, transitions, goto and button targets", () => {
  const d = connect(doc(), "buttons", "end", "ok", "edge1");
  const copy = cloneSelection(d, ["buttons", "end"], "copy");
  const newButton = copy.definition.nodes.find((n) => n.id === "copy_0")!;
  assert.equal(
    (newButton.config.buttons as { target: string }[])[0].target,
    "copy_1",
  );
  assert.equal(copy.definition.edges.at(-1)!.target, "copy_1");
  assert.equal(copy.definition.nodes.length, 5);
});
test("layout is deterministic, finite, covers cycles and preserves domain graph", () => {
  const d = connect(
    connect(doc(), "start", "buttons", "next", "e1"),
    "buttons",
    "start",
    "ok",
    "e2",
  );
  const a = autoLayout(d);
  assert.deepEqual(a, autoLayout(d));
  assert.deepEqual(a.definition, d.definition);
  assert.ok(
    Object.values(a.layout.positions).every(
      (p) => Number.isFinite(p.x) && Number.isFinite(p.y),
    ),
  );
  assert.equal(Object.keys(a.layout.positions).length, 3);
});
test("canonical fingerprint ignores object key insertion order", () => {
  assert.equal(
    canonical({ z: 1, a: { b: 2, a: 3 } }),
    canonical({ a: { a: 3, b: 2 }, z: 1 }),
  );
});
test("late save response keeps edits made in flight and advances confirmed revision", () => {
  const submitted = doc();
  const latest = { ...submitted, name: "ویرایش تازه" };
  const record = {
    ...submitted,
    revision: 8,
    head_revision: 8,
  } as WorkflowRecord;
  const result = mergeSave(latest, submitted, record);
  assert.equal(result.document.name, "ویرایش تازه");
  assert.equal(result.revision, 8);
  assert.equal(result.dirty, true);
  const clean = mergeSave(submitted, submitted, record);
  assert.equal(clean.dirty, false);
});
test("reconciled historical operation never adopts a newer head as its save base", () => {
  const submitted = doc();
  const record = {
    ...submitted,
    revision: 2,
    head_revision: 3,
  } as WorkflowRecord;
  const result = mergeSave({ ...submitted, name: "محلی" }, submitted, record);
  assert.equal(result.revision, 2);
  assert.equal(result.concurrent, true);
});
test("a clipboard snapshot survives deleting or editing its original nodes", () => {
  const original = connect(doc(), "buttons", "end", "ok", "edge1");
  const current = editorReducer(initialEditor(original), {
    type: "remove",
    ids: ["buttons", "end"],
  }).document;
  const pasted = cloneSelection(current, ["buttons", "end"], "copy", original);
  assert.equal(pasted.definition.nodes.length, 3);
  assert.equal(
    pasted.definition.nodes.find((n) => n.id === "copy_0")!.label,
    "منو (کپی)",
  );
  assert.equal(pasted.definition.edges[0].target, "copy_1");
});
