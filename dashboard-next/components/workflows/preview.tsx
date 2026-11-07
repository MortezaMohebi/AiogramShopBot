"use client";
import { useState } from "react";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StudioNav } from "./studio-nav";
import { Field, Select } from "./fields";
import { errorText, workflowRequest } from "@/lib/workflows/client";
import type {
  BotChoice,
  Catalog,
  ChoicePage,
  Platform,
  SimulationEvent,
  SimulationResult,
  WorkflowRecord,
} from "@/lib/workflows/types";
const WorkflowCanvas = dynamic(
  () => import("./canvas").then((m) => m.WorkflowCanvas),
  { ssr: false },
);
/** Replay synthetic events against a pinned immutable revision; no business executors. */
export function WorkflowPreview({
  record,
  catalog,
  initialBots,
}: {
  record: WorkflowRecord;
  catalog: Catalog;
  initialBots: ChoicePage<BotChoice>;
}) {
  const eligible = (b: BotChoice) =>
    record.definition.target_platforms.includes(b.platform) &&
    (record.definition.assignment.mode === "all_eligible" ||
      record.definition.assignment.bot_ids.includes(b.id));
  const [bots, setBots] = useState(initialBots.items),
    [botPage, setBotPage] = useState(initialBots.page),
    [more, setMore] = useState(initialBots.has_more),
    [botId, setBotId] = useState(initialBots.items.find(eligible)?.id ?? ""),
    [platform, setPlatform] = useState<Platform>(
      initialBots.items.find(eligible)?.platform ??
        record.definition.target_platforms[0] ??
        "telegram",
    ),
    [customer, setCustomer] = useState("مشتری آزمایشی"),
    [scenario, setScenario] = useState("standard"),
    [events, setEvents] = useState<SimulationEvent[]>([]),
    [result, setResult] = useState<SimulationResult | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [value, setValue] = useState(""),
    [showGraph, setShowGraph] = useState(false);
  const selected = bots.find((b) => b.id === botId),
    inputKind = result?.input?.kind;
  const replay = async (next: SimulationEvent[]) => {
    if (busy || !botId || !selected || selected.platform !== platform) return;
    setBusy(true);
    setError("");
    try {
      setResult(
        await workflowRequest<SimulationResult>(
          `/${record.id}/simulate`,
          "POST",
          {
            revision: record.revision,
            bot_id: botId,
            platform,
            context: { customer_name: customer, scenario },
            events: next,
          },
        ),
      );
      setEvents(next);
      setValue("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const event = (e: SimulationEvent) => {
    if (events.length >= 100) {
      setError("حداکثر ۱۰۰ تعامل در هر شبیه‌سازی؛ از ابتدا شروع کنید.");
      return;
    }
    void replay([...events, e]);
  };
  const moreBots = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const page = await workflowRequest<ChoicePage<BotChoice>>(
        `/bots?store_id=${record.store_id}&page=${botPage + 1}`,
      );
      setBots((current) => [...current, ...page.items]);
      setBotPage(page.page);
      setMore(page.has_more);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="min-w-0 space-y-5">
      <h1 className="text-2xl font-bold">شبیه‌ساز · {record.name}</h1>
      <p className="text-sm text-muted-foreground">
        نسخهٔ {record.revision} · داده و مشتری آزمایشی
      </p>
      <StudioNav id={record.id} current="preview" />
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm leading-7">
        <strong>فقط شبیه‌سازی.</strong> هیچ پیام، پرداخت، سفارش، تیکت یا مرجوعی
        واقعی ایجاد نمی‌شود. Actionها نتیجهٔ نمونه دارند.
      </div>
      <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(250px,1fr)_minmax(0,2fr)]">
        <aside className="min-w-0 space-y-5 rounded-xl border bg-card p-5">
          <fieldset disabled={busy || Boolean(result)} className="space-y-4">
            <Field label="ربات همان فروشگاه">
              <Select
                label="ربات شبیه‌سازی"
                value={botId}
                options={[
                  { value: "", label: "انتخاب ربات واجد شرایط" },
                  ...bots.filter(eligible).map((b) => ({
                    value: b.id,
                    label: `${b.name} · ${b.platform}`,
                  })),
                ]}
                onChange={(id) => {
                  setBotId(id);
                  const b = bots.find((b) => b.id === id);
                  if (b) setPlatform(b.platform);
                }}
              />
            </Field>
            <Field label="پلتفرم">
              <Select
                label="پلتفرم شبیه‌سازی"
                value={platform}
                options={record.definition.target_platforms.map((p) => ({
                  value: p,
                  label: p === "telegram" ? "Telegram" : "Bale",
                }))}
                onChange={(v) => {
                  const p = v as Platform;
                  setPlatform(p);
                  setBotId(
                    bots.find((b) => eligible(b) && b.platform === p)?.id ?? "",
                  );
                }}
              />
            </Field>
            <Field label="نام مشتری نمونه">
              <Input
                aria-label="نام مشتری نمونه"
                value={customer}
                maxLength={120}
                onChange={(e) => setCustomer(e.target.value)}
              />
            </Field>
            <Field label="دادهٔ نمونه">
              <Select
                label="سناریوی داده"
                value={scenario}
                options={[
                  { value: "standard", label: "سفارش و محصول آزمایشی" },
                  { value: "no_orders", label: "بدون سفارش واجد شرایط" },
                ]}
                onChange={setScenario}
              />
            </Field>
          </fieldset>
          {more && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => void moreBots()}
              disabled={busy}
            >
              ربات‌های بیشتر
            </Button>
          )}
          {!bots.some(eligible) && (
            <p className="text-xs leading-6 text-muted-foreground">
              ربات واجد شرایط در این صفحه پیدا نشد. تخصیص ربات و پلتفرم‌ها را
              بررسی کنید.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy || !botId} onClick={() => void replay([])}>
              {result ? "شروع از ابتدا" : "شروع شبیه‌سازی"}
            </Button>
            {result && (
              <Button
                variant="outline"
                onClick={() => {
                  setResult(null);
                  setEvents([]);
                  setError("");
                }}
                disabled={busy}
              >
                تغییر سناریو
              </Button>
            )}
          </div>
          {error && (
            <p
              role="alert"
              className="break-words text-sm leading-7 text-destructive"
            >
              {error}
            </p>
          )}
          {result && (
            <>
              <div className="space-y-2 border-t pt-4 text-xs">
                <p>
                  وضعیت: <bdi>{result.status}</bdi>
                </p>
                <p>
                  گرهٔ فعال:{" "}
                  <bdi className="break-all">
                    {result.active_node_id ?? "—"}
                  </bdi>
                </p>
                <p>
                  زمان مجازی: {result.elapsed_seconds} ثانیه · تعامل:{" "}
                  {events.length}/100
                </p>
                {result.code && (
                  <p className="break-all text-destructive" dir="ltr">
                    {result.code}
                  </p>
                )}
              </div>
              <details className="rounded-lg border p-3">
                <summary className="cursor-pointer text-sm">
                  متغیرها و مراحل
                </summary>
                <pre
                  dir="ltr"
                  className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs"
                >
                  {JSON.stringify(
                    {
                      values: result.values,
                      visited: result.visited,
                      stub_actions: result.stub_actions,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </>
          )}
        </aside>
        <section
          aria-label="گفت‌وگوی شبیه‌سازی"
          className="flex min-h-[560px] min-w-0 flex-col overflow-hidden rounded-xl border bg-card"
        >
          <div className="flex items-center justify-between border-b bg-muted/30 px-5 py-4">
            <span className="font-semibold">
              {platform === "telegram" ? "Telegram" : "Bale"} Preview
            </span>
            <span className="rounded-full border border-amber-500/40 px-3 py-1 text-xs">
              SIMULATION
            </span>
          </div>
          <div
            className="flex-1 space-y-3 p-4"
            aria-live="polite"
            aria-busy={busy}
          >
            {!result && (
              <p className="py-20 text-center text-sm text-muted-foreground">
                ربات و سناریو را انتخاب کنید و شبیه‌سازی را شروع کنید.
              </p>
            )}
            {result?.messages.map((m, i) => (
              <article
                key={`${m.node_id}-${i}`}
                className={`max-w-[95%] rounded-xl border px-4 py-3 text-sm leading-7 ${m.kind === "input" ? "ms-auto bg-primary/10" : m.kind === "stub" ? "border-amber-500/40 bg-amber-500/10" : "bg-muted/30"}`}
              >
                <p className="mb-1 text-[10px] text-muted-foreground">
                  <bdi>{m.node_id}</bdi> · {m.kind}
                </p>
                <p className="whitespace-pre-wrap break-words">{m.text}</p>
                {m.media_id != null && (
                  <p className="text-xs">رسانهٔ نمونه #{String(m.media_id)}</p>
                )}
              </article>
            ))}
            {result?.validation.issues
              .filter((i) => i.severity === "error")
              .map((i, n) => (
                <p
                  key={n}
                  className="rounded border border-destructive/30 p-3 text-xs leading-6 text-destructive"
                >
                  {i.message}
                </p>
              ))}
          </div>
          {result && (
            <div className="space-y-3 border-t p-4">
              <div className="space-y-2">
                {[...new Set(result.buttons.map((b) => b.row))]
                  .sort((a, b) => a - b)
                  .map((row) => (
                    <div className="flex flex-wrap gap-2" key={row}>
                      {result.buttons
                        .filter((b) => b.row === row)
                        .map((b) => (
                          <Button
                            key={b.key}
                            size="sm"
                            variant="outline"
                            disabled={busy || result.status !== "waiting"}
                            onClick={() =>
                              event({ kind: "button", key: b.key })
                            }
                          >
                            {b.label}
                            {b.type === "url" ? " ↗ نمونه" : ""}
                          </Button>
                        ))}
                    </div>
                  ))}
              </div>
              {result.status === "waiting" &&
                result.input &&
                !["choice", "photo", "document"].includes(
                  String(inputKind),
                ) && (
                  <form
                    className="flex gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      event({ kind: "input", value });
                    }}
                  >
                    <Input
                      aria-label="پاسخ مشتری نمونه"
                      value={value}
                      maxLength={4096}
                      onChange={(e) => setValue(e.target.value)}
                      type={inputKind === "email" ? "email" : "text"}
                      inputMode={
                        inputKind === "number"
                          ? "decimal"
                          : inputKind === "phone"
                            ? "tel"
                            : undefined
                      }
                      placeholder={
                        inputKind === "phone"
                          ? "+989121234567"
                          : "پاسخ آزمایشی…"
                      }
                      disabled={busy}
                    />
                    <Button type="submit" disabled={busy}>
                      ارسال نمونه
                    </Button>
                  </form>
                )}
              {result.status === "waiting" &&
                ["photo", "document"].includes(String(inputKind)) && (
                  <div className="space-y-2">
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        event({
                          kind: "input",
                          file: {
                            name:
                              inputKind === "photo"
                                ? "sample.jpg"
                                : "sample.pdf",
                            mime_type:
                              inputKind === "photo"
                                ? "image/jpeg"
                                : "application/pdf",
                            size_bytes: 1024,
                          },
                        })
                      }
                    >
                      ارسال {inputKind === "photo" ? "تصویر" : "سند"} آزمایشی
                      (۱KB)
                    </Button>
                    <p className="text-xs text-muted-foreground">
                      فایلی بارگذاری نمی‌شود؛ فقط اطلاعات آزمایشی شبیه‌سازی می‌شوند.
                    </p>
                  </div>
                )}
              <div className="flex flex-wrap gap-2 border-t pt-3">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || !result.can_go_back}
                  onClick={() => event({ kind: "back" })}
                >
                  بازگشت
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={
                    busy ||
                    ["completed", "cancelled", "error"].includes(result.status)
                  }
                  onClick={() => event({ kind: "cancel" })}
                >
                  لغو
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={
                    busy ||
                    ["completed", "cancelled", "error"].includes(result.status)
                  }
                  onClick={() => event({ kind: "tick", seconds: 60 })}
                >
                  +۶۰ ثانیهٔ مجازی
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setShowGraph((v) => !v)}
      >
        {showGraph ? "بستن نمودار" : "نمودار و گرهٔ فعال"}
      </Button>
      {showGraph && (
        <WorkflowCanvas
          document={record}
          catalog={catalog}
          selected={[]}
          issues={result?.validation.issues ?? record.validation.issues}
          activeNode={result?.active_node_id}
          disabled
          onSelection={() => {}}
          onPositions={() => {}}
          onViewport={() => {}}
          onConnect={() => {}}
          onRemoveEdges={() => {}}
          onRemoveNodes={() => {}}
          onAdd={() => {}}
        />
      )}
    </div>
  );
}
