"use client";
import { memo, useMemo, useRef } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useReactFlow,
  type Node,
  type NodeProps,
  type NodeChange,
  type EdgeChange,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type {
  Catalog,
  DraftDocument,
  DomainNode,
  Issue,
} from "@/lib/workflows/types";
import { nodePorts } from "@/lib/workflows/state";
type CanvasData = {
  domain: DomainNode;
  ports: string[];
  issues: number;
  active: boolean;
  title: string;
  [key: string]: unknown;
};
type FlowNode = Node<CanvasData, "workflow">;
const StudioNode = memo(function StudioNode({
  data,
  selected,
}: NodeProps<FlowNode>) {
  return (
    <div
      dir="rtl"
      className={`w-52 rounded-xl border bg-card p-3 text-card-foreground shadow-sm ${selected ? "border-primary ring-2 ring-primary/30" : data.active ? "border-emerald-500 ring-2 ring-emerald-500/30" : "border-border"}`}
    >
      <Handle type="target" position={Position.Left} aria-label="ورودی" />
      <div className="text-[10px] text-muted-foreground">{data.title}</div>
      <div className="mt-1 truncate text-sm font-semibold">
        {data.domain.label || data.title}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <code className="truncate text-[10px]" dir="ltr">
          {data.domain.id}
        </code>
        {data.issues > 0 && (
          <span
            className="rounded bg-destructive/10 px-1.5 text-xs text-destructive"
            aria-label={`${data.issues} ایراد`}
          >
            {data.issues}
          </span>
        )}
      </div>
      {data.ports.map((port, i) => (
        <Handle
          key={port}
          id={port}
          type="source"
          position={Position.Right}
          style={{ top: `${((i + 1) / (data.ports.length + 1)) * 100}%` }}
          aria-label={`خروجی ${port}`}
          title={port}
        />
      ))}
    </div>
  );
});
const nodeTypes = { workflow: StudioNode };
interface Props {
  document: DraftDocument;
  catalog: Catalog;
  selected: string[];
  issues: Issue[];
  activeNode?: string | null;
  disabled: boolean;
  onSelection: (ids: string[]) => void;
  onPositions: (
    positions: Record<string, { x: number; y: number }>,
    coalesce: boolean,
  ) => void;
  onViewport: (v: { x: number; y: number; zoom: number }) => void;
  onConnect: (source: string, target: string, port: string) => void;
  onRemoveEdges: (ids: string[]) => void;
  onRemoveNodes: (ids: string[]) => void;
  onAdd: (type: string, position?: { x: number; y: number }) => void;
}
function FlowCanvas(props: Props) {
  const { screenToFlowPosition } = useReactFlow();
  const dragged = useRef(false);
  const nodes = useMemo<FlowNode[]>(
    () =>
      props.document.definition.nodes.map((n) => ({
        id: n.id,
        type: "workflow",
        position: props.document.layout.positions[n.id] ?? { x: 0, y: 0 },
        selected: props.selected.includes(n.id),
        data: {
          domain: n,
          ports: nodePorts(
            n,
            props.catalog.nodes.find((s) => s.type === n.type),
          ),
          issues: props.issues.filter((i) => i.node_id === n.id).length,
          active: props.activeNode === n.id,
          title:
            props.catalog.nodes.find((s) => s.type === n.type)?.label ?? n.type,
        },
      })),
    [
      props.document,
      props.catalog,
      props.selected,
      props.issues,
      props.activeNode,
    ],
  );
  const edges = useMemo(
    () =>
      props.document.definition.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.port,
        label: e.port,
        style: { stroke: "var(--color-muted-foreground)" },
        labelStyle: { fill: "var(--color-foreground)" },
        labelBgStyle: { fill: "var(--color-card)" },
      })),
    [props.document.definition.edges],
  );
  const onNodesChange = (changes: NodeChange<FlowNode>[]) => {
    const removed = changes.filter((c) => c.type === "remove").map((c) => c.id);
    if (removed.length && !props.disabled) props.onRemoveNodes(removed);
    const moves = changes.filter((c) => c.type === "position" && c.position);
    if (moves.length && !props.disabled) {
      const positions = { ...props.document.layout.positions };
      for (const c of moves)
        if (c.type === "position" && c.position) positions[c.id] = c.position;
      props.onPositions(positions, dragged.current);
      dragged.current = true;
    }
    const selects = changes.filter((c) => c.type === "select");
    if (selects.length) {
      const selected = new Set(props.selected);
      for (const c of selects)
        if (c.type === "select") {
          if (c.selected) selected.add(c.id);
          else selected.delete(c.id);
        }
      props.onSelection([...selected]);
    }
  };
  const onEdgesChange = (changes: EdgeChange[]) => {
    if (!props.disabled) {
      const ids = changes.filter((c) => c.type === "remove").map((c) => c.id);
      if (ids.length) props.onRemoveEdges(ids);
    }
  };
  const onConnect = (c: Connection) => {
    if (c.source && c.target && c.sourceHandle && !props.disabled)
      props.onConnect(c.source, c.target, c.sourceHandle);
  };
  return (
    <div
      dir="ltr"
      className="studio-canvas h-[620px] min-h-[420px] w-full overflow-hidden rounded-xl border bg-muted/20"
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDrop={(e) => {
        e.preventDefault();
        const type = e.dataTransfer.getData("application/workflow-node");
        if (!props.disabled && props.catalog.nodes.some((n) => n.type === type))
          props.onAdd(
            type,
            screenToFlowPosition({ x: e.clientX, y: e.clientY }),
          );
      }}
    >
      <ReactFlow<FlowNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={(c) => {
          const source = props.document.definition.nodes.find(
            (n) => n.id === c.source,
          );
          return Boolean(
            source &&
              props.document.definition.nodes.some((n) => n.id === c.target) &&
              c.sourceHandle &&
              nodePorts(
                source,
                props.catalog.nodes.find((s) => s.type === source.type),
              ).includes(c.sourceHandle) &&
              (c.source !== c.target || source.max_visits),
          );
        }}
        onNodeDragStart={() => {
          dragged.current = false;
        }}
        onNodeDragStop={() => {
          dragged.current = false;
        }}
        onMoveEnd={(_, v) => props.onViewport(v)}
        defaultViewport={props.document.layout.viewport}
        nodesDraggable={!props.disabled}
        nodesConnectable={!props.disabled}
        edgesReconnectable={false}
        deleteKeyCode={props.disabled ? null : ["Backspace", "Delete"]}
        multiSelectionKeyCode="Shift"
        selectionKeyCode="Shift"
        snapToGrid
        snapGrid={[20, 20]}
        minZoom={0.15}
        maxZoom={2}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        ariaLabelConfig={{
          "controls.zoomIn.ariaLabel": "بزرگ‌نمایی",
          "controls.zoomOut.ariaLabel": "کوچک‌نمایی",
          "controls.fitView.ariaLabel": "نمایش همهٔ گره‌ها",
          "controls.interactive.ariaLabel": "تغییر قفل Canvas",
          "minimap.ariaLabel": "نقشهٔ فرایند",
          "node.a11yDescription.default":
            "برای انتخاب Enter و برای جابه‌جایی کلیدهای جهت را بزنید. اتصال از بخش ویژگی‌ها نیز در دسترس است.",
        }}
      >
        <Background gap={20} />
        <Controls />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => (n.selected ? "#6d5dfc" : "#64748b")}
        />
      </ReactFlow>
    </div>
  );
}
export function WorkflowCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <FlowCanvas {...props} />
    </ReactFlowProvider>
  );
}
