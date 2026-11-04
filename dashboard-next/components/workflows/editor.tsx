"use client";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  Copy,
  Download,
  LayoutGrid,
  Plus,
  Redo2,
  Save,
  Trash2,
  Undo2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Inspector } from "./inspector";
import { WorkflowActions } from "./workflow-actions";
import { WorkflowSettings } from "./settings-form";
import { StudioNav } from "./studio-nav";
import { useDraftSave } from "./use-draft-save";
import {
  autoLayout,
  canonical,
  cloneSelection,
  connect,
  disconnect,
  editorReducer,
  initialEditor,
  nodePorts,
} from "@/lib/workflows/state";
import { errorText, workflowRequest } from "@/lib/workflows/client";
import type {
  Catalog,
  DraftDocument,
  DomainNode,
  ValidationReport,
  WorkflowButton,
  WorkflowRecord,
} from "@/lib/workflows/types";
const WorkflowCanvas = dynamic(
  () => import("./canvas").then((m) => m.WorkflowCanvas),
  {
    ssr: false,
    loading: () => (
      <div
        className="flex h-[620px] items-center justify-center rounded-xl border text-sm"
        role="status"
      >
        در حال آماده‌سازی Canvas…
      </div>
    ),
  },
);
export function WorkflowEditor({
  initial,
  catalog,
  settings = false,
}: {
  initial: WorkflowRecord;
  catalog: Catalog;
  settings?: boolean;
}) {
  const [state, dispatch] = useReducer(editorReducer, initial, initialEditor),
    [selected, setSelected] = useState<string[]>([]),
    [query, setQuery] = useState(""),
    [showCanvas, setShowCanvas] = useState(false),
    [panel, setPanel] = useState<"nodes" | "variables">("nodes"),
    [manualValidation, setValidation] = useState<ValidationReport | null>(null),
    [validationError, setValidationError] = useState(""),
    [validating, setValidating] = useState(false);
  const clipboard = useRef<{ document: DraftDocument; ids: string[] } | null>(
      null,
    ),
    lastEdit = useRef({ key: "", at: 0 });
  const doc = state.document;
  const replace = useCallback(
    (document: DraftDocument) => dispatch({ type: "replace", document }),
    [],
  );
  const saving = useDraftSave(initial, doc, replace),
    disabled = !saving.record.can_write || saving.record.status !== "draft";
  const validation = manualValidation ?? saving.record.validation;
  const edit = useCallback(
    (document: DraftDocument, key = "", forceCoalesce?: boolean) => {
      if (disabled) return;
      setValidation(null);
      const now = Date.now();
      const coalesce =
        forceCoalesce ??
        (Boolean(key) &&
          lastEdit.current.key === key &&
          now - lastEdit.current.at < 700);
      dispatch({ type: "edit", document, coalesce });
      lastEdit.current = { key, at: now };
    },
    [disabled],
  );
  const add = (type: string, position?: { x: number; y: number }) => {
    const spec = catalog.nodes.find((n) => n.type === type);
    if (
      !spec ||
      disabled ||
      doc.definition.nodes.length >= catalog.limits.nodes
    )
      return;
    const id = `node_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
    edit({
      ...doc,
      definition: {
        ...doc.definition,
        nodes: [
          ...doc.definition.nodes,
          {
            id,
            type,
            label: spec.label,
            config: structuredClone(spec.defaults),
            platform_overrides: {},
            max_visits: null,
          },
        ],
      },
      layout: {
        ...doc.layout,
        positions: {
          ...doc.layout.positions,
          [id]: position ?? { x: doc.definition.nodes.length * 80, y: 80 },
        },
      },
    });
    setSelected([id]);
  };
  const updateNode = (node: DomainNode) => {
    let next = {
      ...doc,
      definition: {
        ...doc.definition,
        nodes: doc.definition.nodes.map((n) => (n.id === node.id ? node : n)),
      },
    };
    const ports = nodePorts(
      node,
      catalog.nodes.find((s) => s.type === node.type),
    );
    next = {
      ...next,
      definition: {
        ...next.definition,
        edges: next.definition.edges.filter(
          (e) => e.source !== node.id || ports.includes(e.port),
        ),
      },
    };
    if (node.type === "show_buttons") {
      next = {
        ...next,
        definition: {
          ...next.definition,
          edges: next.definition.edges.filter((e) => e.source !== node.id),
        },
      };
      for (const b of node.config.buttons as WorkflowButton[])
        if (b.target && ["callback", "action"].includes(b.type))
          next = connect(
            next,
            node.id,
            b.target,
            b.key,
            `edge_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
          );
    }
    if (node.type === "go_to_step") {
      next = {
        ...next,
        definition: {
          ...next.definition,
          edges: next.definition.edges.filter((e) => e.source !== node.id),
        },
      };
      if (node.config.target)
        next = connect(
          next,
          node.id,
          String(node.config.target),
          "next",
          `edge_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
        );
    }
    edit(next, `node:${node.id}`);
  };
  const wire = (source: string, target: string, port: string) => {
    if (!target) {
      edit(
        disconnect(
          doc,
          doc.definition.edges
            .filter((e) => e.source === source && e.port === port)
            .map((e) => e.id),
        ),
      );
      return;
    }
    edit(
      connect(
        doc,
        source,
        target,
        port,
        `edge_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
      ),
    );
  };
  const remove = useCallback(
    (ids: string[]) => {
      if (!disabled) {
        dispatch({ type: "remove", ids });
        setSelected([]);
      }
    },
    [disabled],
  );
  const paste = useCallback(() => {
    if (!disabled && clipboard.current?.ids.length)
      dispatch({
        type: "edit",
        document: cloneSelection(
          doc,
          clipboard.current!.ids,
          `copy_${crypto.randomUUID().slice(0, 8)}`,
          clipboard.current!.document,
        ),
      });
  }, [disabled, doc]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        e.target instanceof Element &&
        e.target.closest("input,textarea,select,[contenteditable=true]")
      )
        return;
      if (!(e.ctrlKey || e.metaKey) || disabled) return;
      const k = e.key.toLowerCase();
      if (k === "z") {
        e.preventDefault();
        dispatch({ type: e.shiftKey ? "redo" : "undo" });
      }
      if (k === "y") {
        e.preventDefault();
        dispatch({ type: "redo" });
      }
      if (k === "c") {
        e.preventDefault();
        clipboard.current = {
          document: structuredClone(doc),
          ids: [...selected],
        };
      }
      if (k === "v") {
        e.preventDefault();
        paste();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [disabled, paste, selected, doc]);
  const validate = async () => {
    setValidating(true);
    setValidationError("");
    try {
      setValidation(
        await workflowRequest<ValidationReport>(
          `/${initial.id}/validate`,
          "POST",
          { definition: doc.definition },
        ),
      );
    } catch (e) {
      setValidationError(errorText(e));
    } finally {
      setValidating(false);
    }
  };
  const download = () => {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              schema_version: 1,
              name: doc.name,
              description: doc.description,
              definition: doc.definition,
              layout: doc.layout,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const a = window.document.createElement("a");
    a.href = url;
    a.download = `workflow-${initial.key}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const node = doc.definition.nodes.find((n) => n.id === selected[0]);
  const specs = catalog.nodes.filter((n) =>
    `${n.label} ${n.type} ${n.group}`
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  return (
    <div className="min-w-0 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link href="/studio/workflows" className="text-xs text-primary">
            فرایندهای فروشگاه
          </Link>
          <h1 className="mt-2 break-words text-2xl font-bold">{doc.name}</h1>
          <p className="mt-2 text-xs text-muted-foreground">
            <bdi>{initial.key}</bdi> · Revision {saving.record.revision} ·{" "}
            {saving.record.status === "draft"
              ? "پیش‌نویس"
              : saving.record.status === "archived"
                ? "بایگانی"
                : "حذف‌شده"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={download}>
            <Download />
            دریافت JSON
          </Button>
          <Button
            size="sm"
            disabled={
              disabled ||
              saving.status === "saving" ||
              saving.status === "unknown" ||
              saving.status === "conflict" ||
              !saving.dirty
            }
            onClick={() => void saving.save()}
          >
            <Save />
            ذخیره
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled
            title="Runtime اجرای فرایند هنوز آماده نیست"
          >
            انتشار · در دسترس نیست
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 rounded-lg border bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
        <span>
          Store: <bdi className="break-all">{initial.store_id}</bdi>
        </span>
        <span>
          ربات‌ها:{" "}
          {doc.definition.assignment.mode === "all_eligible"
            ? "همهٔ ربات‌های واجد شرایط فروشگاه"
            : `${doc.definition.assignment.bot_ids.length} ربات انتخاب‌شده`}
        </span>
        <span>
          اعتبارسنجی:{" "}
          {validation.issues.filter((i) => i.severity === "error").length} خطا ·{" "}
          {validation.issues.filter((i) => i.severity === "warning").length}{" "}
          هشدار
        </span>
        <span>
          آخرین ذخیره:{" "}
          {saving.record.updated_at
            ? new Date(saving.record.updated_at).toLocaleString("fa-IR", {
                timeZone: "Asia/Tehran",
              })
            : "—"}
        </span>
      </div>
      <StudioNav id={initial.id} current={settings ? "settings" : "editor"} />
      <div
        className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-3 text-xs"
        role="status"
        aria-live="polite"
      >
        <span
          className={`size-2 rounded-full ${saving.status === "idle" && !saving.dirty ? "bg-emerald-500" : saving.status === "conflict" || saving.status === "error" ? "bg-destructive" : "bg-amber-500"}`}
        />
        <span>
          {saving.status === "saving"
            ? "در حال ذخیره / بررسی رسید…"
            : saving.status === "unknown"
              ? "نتیجهٔ ذخیره نامشخص"
              : saving.status === "conflict"
                ? "تعارض نسخه"
                : saving.status === "error"
                  ? "ذخیره انجام نشد"
                  : saving.dirty
                    ? "تغییر ذخیره‌نشده · ذخیرهٔ خودکار"
                    : "همهٔ تغییرات تأیید شده‌اند"}
        </span>
        <span className="text-muted-foreground">
          Studio فقط پیش‌نویس و شبیه‌سازی
        </span>
      </div>
      {saving.error && (
        <div
          role="alert"
          className="space-y-3 rounded-lg border border-amber-500/50 bg-amber-500/10 p-4 text-sm"
        >
          <p className="break-words leading-7">{saving.error}</p>
          <div className="flex flex-wrap gap-2">
            {saving.status === "unknown" && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void saving.reconcile()}
                >
                  بررسی رسید ذخیره
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void saving.retry()}
                >
                  تکرار همان عملیات
                </Button>
              </>
            )}
            {saving.status === "conflict" && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    download();
                    void saving.loadRemote();
                  }}
                >
                  دریافت JSON محلی و بارگذاری سرور
                </Button>
                <Link
                  className="text-primary underline"
                  href={`/studio/workflows/${initial.id}/versions`}
                >
                  مقایسهٔ نسخه‌ها
                </Link>
              </>
            )}
            {saving.status === "error" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void saving.save()}
              >
                تلاش پس از اصلاح فیلدها
              </Button>
            )}
          </div>
        </div>
      )}
      {disabled && (
        <p className="rounded-lg border bg-muted/40 p-4 text-sm leading-7">
          این نسخه فقط خواندنی است.
          {saving.record.status !== "draft"
            ? " برای ادامه، نسخه‌ای را از تاریخچه به پیش‌نویس جدید بازگردانید."
            : " ویرایش به مجوز محتوا و فروشگاه جاری با دسترسی ویرایش نیاز دارد."}
        </p>
      )}
      {settings ? (
        <>
          <WorkflowSettings
            document={doc}
            onChange={(d) => edit(d, "settings")}
            storeId={initial.store_id}
            disabled={disabled}
          />
          <WorkflowActions
            record={saving.record}
            disabled={saving.dirty || saving.status !== "idle"}
          />
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="icon"
              variant="outline"
              aria-label="Undo"
              disabled={disabled || !state.past.length}
              onClick={() => dispatch({ type: "undo" })}
            >
              <Undo2 />
            </Button>
            <Button
              size="icon"
              variant="outline"
              aria-label="Redo"
              disabled={disabled || !state.future.length}
              onClick={() => dispatch({ type: "redo" })}
            >
              <Redo2 />
            </Button>
            <Button
              size="icon"
              variant="outline"
              aria-label="کپی گره‌های انتخاب‌شده"
              disabled={disabled || !selected.length}
              onClick={() => {
                clipboard.current = {
                  document: structuredClone(doc),
                  ids: [...selected],
                };
              }}
            >
              <Copy />
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={paste}
            >
              Paste
            </Button>
            <Button
              size="icon"
              variant="outline"
              aria-label="حذف گره‌های انتخاب‌شده"
              disabled={disabled || !selected.length}
              onClick={() => remove(selected)}
            >
              <Trash2 />
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={() => edit(autoLayout(doc))}
            >
              <LayoutGrid />
              چیدمان خودکار
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={disabled || selected.length < 2}
              onClick={() => {
                const positions = { ...doc.layout.positions };
                const x = positions[selected[0]]?.x ?? 0;
                for (const id of selected)
                  positions[id] = { x, y: positions[id]?.y ?? 0 };
                edit({ ...doc, layout: { ...doc.layout, positions } });
              }}
            >
              هم‌ترازی
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="xl:hidden"
              onClick={() => setShowCanvas((v) => !v)}
            >
              {showCanvas ? "فهرست مراحل" : "نمایش Canvas"}
            </Button>
          </div>
          <div className="grid min-w-0 gap-4 xl:grid-cols-[200px_minmax(0,1fr)_300px]">
            <aside className="min-w-0 rounded-xl border bg-card p-3">
              <div className="mb-3 flex gap-2">
                <Button
                  size="sm"
                  variant={panel === "nodes" ? "secondary" : "ghost"}
                  onClick={() => setPanel("nodes")}
                >
                  گره‌ها
                </Button>
                <Button
                  size="sm"
                  variant={panel === "variables" ? "secondary" : "ghost"}
                  onClick={() => setPanel("variables")}
                >
                  راهنما
                </Button>
              </div>
              {panel === "nodes" ? (
                <>
                  <Input
                    aria-label="جستجوی گره"
                    placeholder="جستجوی گره…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  <div className="mt-3 grid max-h-60 grid-cols-2 gap-2 overflow-y-auto xl:max-h-[550px] xl:grid-cols-1">
                    {specs.map((s) => (
                      <button
                        type="button"
                        key={s.type}
                        draggable={!disabled}
                        disabled={disabled}
                        onDragStart={(e) =>
                          e.dataTransfer.setData(
                            "application/workflow-node",
                            s.type,
                          )
                        }
                        onClick={() => add(s.type)}
                        className="min-w-0 rounded-lg border bg-background p-3 text-start text-xs transition hover:border-primary focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
                      >
                        <span className="mb-1 block text-[10px] text-muted-foreground">
                          {s.group}
                        </span>
                        <span className="flex items-center gap-1 font-medium">
                          <Plus className="size-3 shrink-0" />
                          {s.label}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <div className="space-y-3 text-xs leading-7 text-muted-foreground">
                  <p>
                    افزودن با کلیک یا Drag & Drop. چندانتخاب با Shift؛ Undo با
                    Ctrl+Z.
                  </p>
                  <p>
                    متغیرها، Entry Point و تخصیص ربات در تنظیمات همین فرایند
                    ویرایش می‌شوند.
                  </p>
                  <p dir="ltr" className="break-all">
                    {"{{variable_name}}"}
                  </p>
                  <Link
                    className="text-primary underline"
                    href={`/studio/workflows/${initial.id}/settings`}
                  >
                    بازکردن تنظیمات و متغیرها
                  </Link>
                </div>
              )}
            </aside>
            <section className="min-w-0">
              <div className={showCanvas ? "block" : "hidden xl:block"}>
                <WorkflowCanvas
                  document={doc}
                  catalog={catalog}
                  selected={selected}
                  issues={validation.issues}
                  disabled={disabled}
                  onSelection={setSelected}
                  onPositions={(positions, coalesce) =>
                    edit(
                      { ...doc, layout: { ...doc.layout, positions } },
                      "drag",
                      coalesce,
                    )
                  }
                  onViewport={(viewport) => {
                    if (
                      !disabled &&
                      canonical(viewport) !== canonical(doc.layout.viewport)
                    )
                      edit(
                        { ...doc, layout: { ...doc.layout, viewport } },
                        "viewport",
                      );
                  }}
                  onConnect={wire}
                  onRemoveEdges={(ids) => edit(disconnect(doc, ids))}
                  onRemoveNodes={remove}
                  onAdd={add}
                />
              </div>
              <div
                className={`${showCanvas ? "hidden" : "block"} space-y-2 xl:hidden`}
                aria-label="فهرست مراحل"
              >
                {doc.definition.nodes.map((n, i) => (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => setSelected([n.id])}
                    className={`flex w-full min-w-0 items-center justify-between gap-3 rounded-lg border bg-card p-4 text-start text-sm focus-visible:outline-2 focus-visible:outline-ring ${selected.includes(n.id) ? "border-primary ring-1 ring-primary" : "border-border"}`}
                  >
                    <span className="min-w-0 break-words">
                      {i + 1}. {n.label || n.type}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {
                        doc.definition.edges.filter((e) => e.source === n.id)
                          .length
                      }{" "}
                      خروجی
                    </span>
                  </button>
                ))}
                {!doc.definition.nodes.length && (
                  <p className="rounded-xl border border-dashed p-8 text-sm">
                    از فهرست گره‌ها، «شروع» را اضافه کنید.
                  </p>
                )}
              </div>
            </section>
            <aside className="min-w-0 rounded-xl border bg-card p-4 xl:max-h-[620px] xl:overflow-y-auto">
              {node ? (
                <Inspector
                  key={node.id}
                  node={node}
                  definition={doc.definition}
                  catalog={catalog}
                  issues={validation.issues.filter(
                    (i) => i.node_id === node.id,
                  )}
                  storeId={initial.store_id}
                  onNode={updateNode}
                  onConnect={(port, target) => wire(node.id, target, port)}
                  onDelete={() => remove([node.id])}
                  disabled={disabled}
                />
              ) : (
                <div className="space-y-3 py-8 text-sm leading-7 text-muted-foreground">
                  <p className="font-semibold text-foreground">
                    ویژگی‌های مرحله
                  </p>
                  <p>
                    یک گره را در Canvas یا فهرست مراحل انتخاب کنید. اتصال
                    خروجی‌ها با کنترل مقصد در همین بخش نیز ممکن است.
                  </p>
                </div>
              )}
            </aside>
          </div>
        </>
      )}
      <section className="rounded-xl border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">اعتبارسنجی</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              نتیجهٔ آخرین بررسی؛ پیش‌نویس ناقص هم ذخیره می‌شود.
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={validating}
            onClick={() => void validate()}
          >
            {validating ? "در حال بررسی…" : "بررسی تعریف فعلی"}
          </Button>
        </div>
        {validationError && (
          <p role="alert" className="mt-3 text-sm text-destructive">
            {validationError}
          </p>
        )}
        <div className="mt-4 space-y-2">
          {validation.issues.map((issue, i) => (
            <button
              type="button"
              key={`${issue.code}-${i}`}
              onClick={() => {
                if (issue.node_id) setSelected([issue.node_id]);
              }}
              className={`block w-full rounded-lg border px-3 py-2 text-start text-xs leading-6 ${issue.severity === "error" ? "border-destructive/30 text-destructive" : "border-amber-500/30 text-foreground"}`}
            >
              <span className="font-semibold">
                {issue.severity === "error" ? "خطا" : "هشدار"}
              </span>{" "}
              · {issue.message}{" "}
              {issue.platform && <bdi>({issue.platform})</bdi>}
              <code className="ms-2 text-[10px]" dir="ltr">
                {issue.code}
              </code>
            </button>
          ))}
          {!validation.issues.length && (
            <p className="text-sm text-emerald-600 dark:text-emerald-400">
              تعریف در آخرین بررسی معتبر بود. انتشار به Runtime نیاز دارد.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
