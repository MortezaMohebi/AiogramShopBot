"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, Select } from "@/components/workflows/fields";
import { actionRequest, ActionRequestError } from "@/lib/actions/client";
import {
  actionReason,
  filterActions,
  parseActionInput,
  primitiveSchema,
  sideEffectLabels,
} from "@/lib/actions/state";
import type {
  ActionCatalogPage,
  ActionDescriptor,
  ActionResult,
} from "@/lib/actions/types";
import type { BotChoice, ChoicePage } from "@/lib/workflows/types";

function identity(action: ActionDescriptor) {
  return `${action.key}@${action.version}`;
}
/** Safe dry-run never offers customer selection, approval minting or a live execute button. */
function DryRunForm({
  action,
  bot,
}: {
  action: ActionDescriptor;
  bot: BotChoice;
}) {
  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(
      Object.entries(action.input_schema.properties ?? {}).flatMap(
        ([key, field]) =>
          field.default === undefined || field.default === null
            ? []
            : [[key, String(field.default)]],
      ),
    ),
  );
  const [result, setResult] = useState<ActionResult | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const run = async () => {
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const input = parseActionInput(action.input_schema, values);
      const response = await actionRequest<ActionResult>("/dry-run", "POST", {
        action_key: action.key,
        action_version: action.version,
        bot_id: bot.id,
        platform: bot.platform,
        input,
      });
      if (alive.current) setResult(response);
    } catch (error) {
      if (alive.current)
        setError(
          actionReason(
            error instanceof ActionRequestError
              ? error.code
              : error instanceof Error
                ? error.message
                : "service_unavailable",
          ),
        );
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  return (
    <section
      className="space-y-4 rounded-lg border p-4"
      aria-label="بررسی بدون تغییر"
    >
      <h3 className="font-semibold">Dry-run</h3>
      <p className="text-xs leading-6 text-muted-foreground">
        دادهٔ واقعی کاتالوگ را با دسترسی همین ربات می‌خواند. سبد، سفارش و پرداخت
        تغییر نمی‌کنند.
      </p>
      {Object.entries(action.input_schema.properties ?? {}).map(
        ([key, raw]) => {
          const field = primitiveSchema(raw),
            label = `${key}${action.input_schema.required?.includes(key) ? " *" : ""}`;
          return (
            <Field key={key} label={label}>
              {field.enum ? (
                <Select
                  label={key}
                  value={String(values[key] ?? "")}
                  onChange={(value) =>
                    setValues((old) => ({ ...old, [key]: value }))
                  }
                  options={[
                    { value: "", label: "پیش‌فرض Action" },
                    ...field.enum.map((value) => ({
                      value: String(value),
                      label: String(value),
                    })),
                  ]}
                />
              ) : field.type === "boolean" ? (
                <Select
                  label={key}
                  value={String(values[key] ?? "")}
                  onChange={(value) =>
                    setValues((old) => ({ ...old, [key]: value }))
                  }
                  options={[
                    { value: "", label: "پیش‌فرض Action" },
                    { value: "true", label: "درست" },
                    { value: "false", label: "نادرست" },
                  ]}
                />
              ) : (
                <Input
                  aria-label={key}
                  dir={field.type === "integer" ? "ltr" : undefined}
                  type={field.type === "integer" ? "number" : "text"}
                  min={field.minimum}
                  max={field.maximum}
                  maxLength={field.maxLength}
                  value={String(values[key] ?? "")}
                  onChange={(event) =>
                    setValues((old) => ({ ...old, [key]: event.target.value }))
                  }
                />
              )}
            </Field>
          );
        },
      )}
      <Button type="button" disabled={busy} onClick={() => void run()}>
        {busy ? "در حال بررسی…" : "اجرای Dry-run"}
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {result && (
        <div role="status" className="space-y-2 text-sm">
          <p>
            {result.status === "succeeded" && result.dry_run
              ? "بررسی بدون تغییر انجام شد."
              : result.error
                ? actionReason(result.error.code)
                : "پیش‌نمایش دقیق در دسترس نیست."}
          </p>
          {result.output && (
            <pre
              dir="ltr"
              className="max-h-80 max-w-full overflow-auto rounded bg-muted p-3 text-xs"
            >
              {JSON.stringify(result.output, null, 2)}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}

/** Real metadata/context reads are cancellable by selection; stale results never enable a new Bot. */
export function ActionCatalog({
  initial,
  bots: initialBots,
}: {
  initial: ActionCatalogPage;
  bots: ChoicePage<BotChoice>;
}) {
  const [filters, setFilters] = useState({
    q: "",
    category: "",
    effect: "",
    deprecated: "all",
  });
  const [botId, setBotId] = useState(""),
    [selectedKey, setSelectedKey] = useState("");
  const [bots, setBots] = useState(initialBots),
    [botLoading, setBotLoading] = useState(false);
  const [observed, setObserved] = useState({
    key: "",
    data: initial,
    error: "",
  });
  const [moreLoading, setMoreLoading] = useState(false);
  const detailRef = useRef<HTMLElement>(null);
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.category) params.set("category", filters.category);
  if (filters.effect) params.set("side_effect", filters.effect);
  if (filters.deprecated !== "all")
    params.set("deprecated", filters.deprecated);
  if (botId) params.set("bot_id", botId);
  const requestKey = params.toString(),
    loading = observed.key !== requestKey;
  useEffect(() => {
    if (observed.key === requestKey) return;
    let active = true;
    const timer = setTimeout(() => {
      void actionRequest<ActionCatalogPage>(
        requestKey ? `?${requestKey}` : "",
      ).then(
        (data) => {
          if (active) setObserved({ key: requestKey, data, error: "" });
        },
        (error) => {
          if (active)
            setObserved({
              key: requestKey,
              data: { ...initial, items: [], total: 0, has_more: false },
              error: actionReason(
                error instanceof ActionRequestError
                  ? error.code
                  : "service_unavailable",
              ),
            });
        },
      );
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [requestKey, observed.key, initial]);
  const data = observed.data,
    items = filterActions(data.items, filters);
  const selected =
    items.find((item) => identity(item) === selectedKey) ?? items[0];
  const bot = bots.items.find((item) => item.id === botId);
  const loadBots = async () => {
    setBotLoading(true);
    try {
      const next = await actionRequest<ChoicePage<BotChoice>>(
        `/bots?page=${bots.page + 1}`,
      );
      setBots((old) => ({ ...next, items: [...old.items, ...next.items] }));
    } catch (error) {
      setObserved((old) => ({
        ...old,
        error: actionReason(
          error instanceof ActionRequestError
            ? error.code
            : "service_unavailable",
        ),
      }));
    } finally {
      setBotLoading(false);
    }
  };
  const loadMore = async () => {
    const key = requestKey;
    setMoreLoading(true);
    try {
      const next = await actionRequest<ActionCatalogPage>(
        `?${key}${key ? "&" : ""}page=${data.page + 1}`,
      );
      setObserved((old) =>
        old.key === key
          ? {
              key,
              data: { ...next, items: [...old.data.items, ...next.items] },
              error: "",
            }
          : old,
      );
    } catch (error) {
      setObserved((old) =>
        old.key === key
          ? {
              ...old,
              error: actionReason(
                error instanceof ActionRequestError
                  ? error.code
                  : "service_unavailable",
              ),
            }
          : old,
      );
    } finally {
      setMoreLoading(false);
    }
  };
  return (
    <div className="min-w-0 space-y-5">
      <div className="grid gap-3 rounded-xl border bg-card p-4 sm:grid-cols-2 xl:grid-cols-5">
        <Field label="جستجوی Action">
          <Input
            aria-label="جستجوی Action"
            value={filters.q}
            maxLength={100}
            onChange={(event) =>
              setFilters((old) => ({ ...old, q: event.target.value }))
            }
          />
        </Field>
        <Field label="گروه">
          <Select
            label="گروه Action"
            value={filters.category}
            onChange={(category) => setFilters((old) => ({ ...old, category }))}
            options={[
              { value: "", label: "همهٔ گروه‌ها" },
              ...[
                "catalog",
                "cart",
                "order",
                "checkout",
                "support",
                "returns",
                "wholesale",
                "notification",
              ].map((value) => ({ value, label: value })),
            ]}
          />
        </Field>
        <Field label="اثر جانبی">
          <Select
            label="اثر جانبی"
            value={filters.effect}
            onChange={(effect) => setFilters((old) => ({ ...old, effect }))}
            options={[
              { value: "", label: "همهٔ اثرها" },
              ...Object.entries(sideEffectLabels).map(([value, label]) => ({
                value,
                label,
              })),
            ]}
          />
        </Field>
        <Field label="وضعیت نسخه">
          <Select
            label="وضعیت نسخه"
            value={filters.deprecated}
            onChange={(deprecated) =>
              setFilters((old) => ({ ...old, deprecated }))
            }
            options={[
              { value: "all", label: "همهٔ نسخه‌ها" },
              { value: "false", label: "نسخه‌های جاری" },
              { value: "true", label: "نسخه‌های منسوخ" },
            ]}
          />
        </Field>
        <Field label="Context ربات">
          <Select
            label="Context ربات"
            value={botId}
            onChange={setBotId}
            options={[
              { value: "", label: "انتخاب ربات" },
              ...bots.items.map((item) => ({
                value: item.id,
                label: `${item.name} · ${item.platform} · ${item.status}`,
              })),
            ]}
          />
        </Field>
        {bots.has_more && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={botLoading}
            onClick={() => void loadBots()}
          >
            ربات‌های بیشتر
          </Button>
        )}
      </div>
      <p className="text-xs leading-6 text-muted-foreground">
        فروشگاه و دسترسی از نشست شما مشخص می‌شوند. انتخاب ربات فقط دسترسی Action
        را بررسی می‌کند؛ Runtime در این مرحله فعال نیست.
      </p>
      {observed.error && (
        <p
          role="alert"
          className="rounded border border-destructive/30 p-3 text-sm text-destructive"
        >
          {observed.error}
        </p>
      )}
      <p role="status" className="text-xs text-muted-foreground">
        {loading
          ? "در حال بررسی Context و Actionها…"
          : `${data.total.toLocaleString("fa-IR")} Action پیدا شد.`}
      </p>
      <div className="grid min-w-0 items-start gap-5 lg:grid-cols-[minmax(16rem,1fr)_minmax(0,2fr)]">
        <section
          className="min-w-0 rounded-xl border bg-card p-2"
          aria-label="فهرست Actionها"
          aria-busy={loading}
        >
          <div className="max-h-96 space-y-1 overflow-y-auto p-1 lg:max-h-[42rem]">
            {items.map((item) => (
              <button
                type="button"
                key={identity(item)}
                aria-pressed={selected && identity(selected) === identity(item)}
                className={`w-full rounded-lg border px-3 py-3 text-start focus-visible:outline-2 focus-visible:outline-ring ${selected && identity(selected) === identity(item) ? "border-primary bg-primary/5" : "border-transparent hover:bg-muted"}`}
                onClick={() => {
                  setSelectedKey(identity(item));
                  if (window.matchMedia("(max-width: 767px)").matches)
                    detailRef.current?.scrollIntoView({ block: "start" });
                }}
              >
                <span className="block text-sm font-semibold">{item.name}</span>
                <bdi
                  dir="ltr"
                  className="mt-1 block break-all text-[11px] text-muted-foreground"
                >
                  {identity(item)}
                </bdi>
                <span className="mt-2 block text-[11px] text-muted-foreground">
                  {sideEffectLabels[item.side_effect]}
                  {item.deprecated ? " · منسوخ" : ""}
                </span>
              </button>
            ))}
            {!items.length && !loading && (
              <p className="p-4 text-sm text-muted-foreground">
                Actionی با این فیلترها پیدا نشد.
              </p>
            )}
          </div>
          {data.has_more && (
            <Button
              className="m-2"
              type="button"
              variant="outline"
              disabled={loading || moreLoading}
              onClick={() => void loadMore()}
            >
              Actionهای بیشتر
            </Button>
          )}
        </section>
        <section
          ref={detailRef}
          className="min-w-0 scroll-mt-24 space-y-5"
          aria-label="جزئیات Action"
        >
          {selected ? (
            <>
              <div className="space-y-4 rounded-xl border bg-card p-5">
                <h2 className="text-lg font-semibold">{selected.name}</h2>
                <bdi
                  dir="ltr"
                  className="block break-all text-xs text-muted-foreground"
                >
                  {identity(selected)}
                </bdi>
                <p className="text-sm leading-7">{selected.description}</p>
                {selected.deprecated && (
                  <p className="rounded border p-3 text-sm">
                    این نسخه منسوخ است.
                    {selected.replacement && (
                      <bdi dir="ltr" className="ms-2 break-all">
                        {selected.replacement}
                      </bdi>
                    )}
                  </p>
                )}
                <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
                  {[
                    ["اثر جانبی", sideEffectLabels[selected.side_effect]],
                    [
                      "Confirmation",
                      ["customer_confirmation", "both"].includes(
                        selected.confirmation,
                      )
                        ? "تأیید مشتری لازم است"
                        : "لازم نیست",
                    ],
                    [
                      "Approval",
                      ["operator_approval", "both"].includes(
                        selected.confirmation,
                      )
                        ? "تأیید مسئول لازم است"
                        : "لازم نیست",
                    ],
                    ["Idempotency", selected.idempotency],
                    ["مهلت اجرا", `${selected.timeout_seconds} ثانیه`],
                    [
                      "Retry",
                      `حداکثر ${selected.max_retries} · ${selected.backoff_seconds} ثانیه فاصله`,
                    ],
                    ["پیام‌رسان‌ها", selected.platforms.join(" / ")],
                    [
                      "شبیه‌ساز",
                      selected.simulator === "deterministic"
                        ? "دادهٔ مصنوعی و بدون اثر واقعی"
                        : "در دسترس نیست",
                    ],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className="text-xs text-muted-foreground">{label}</dt>
                      <dd className="mt-1 break-words">{value}</dd>
                    </div>
                  ))}
                </dl>
                <div
                  className="space-y-2 rounded-lg border p-3 text-sm"
                  aria-label="دسترسی Action"
                >
                  <p>
                    {loading
                      ? "در حال بررسی Context…"
                      : selected.availability?.available
                        ? "سرویس برای این ربات آماده است؛ اجرای Workflow هنوز فعال نیست."
                        : "Action برای این Context آماده نیست."}
                  </p>
                  {!loading &&
                    selected.availability?.reasons.map((reason) => (
                      <p
                        key={reason}
                        className="text-xs leading-6 text-muted-foreground"
                      >
                        {actionReason(reason)}
                      </p>
                    ))}
                </div>
                <details className="rounded border p-3">
                  <summary className="cursor-pointer text-sm">
                    قرارداد ورودی و خروجی
                  </summary>
                  <div className="min-w-0 space-y-3 pt-3">
                    {[
                      ["Input", selected.input_schema],
                      ["Output", selected.output_schema],
                      ["Errors", selected.error_schema],
                    ].map(([label, schema]) => (
                      <div key={String(label)}>
                        <h3 className="mb-1 text-xs font-semibold">
                          {String(label)}
                        </h3>
                        <pre
                          dir="ltr"
                          className="max-h-64 max-w-full overflow-auto rounded bg-muted p-3 text-xs"
                        >
                          {JSON.stringify(schema, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                </details>
              </div>
              {!loading && selected.can_dry_run && bot && (
                <DryRunForm
                  key={`${identity(selected)}:${bot.id}`}
                  action={selected}
                  bot={bot}
                />
              )}
              {!loading && !selected.can_dry_run && (
                <p className="rounded border p-4 text-xs leading-6 text-muted-foreground">
                  Dry-run این صفحه برای خواندن کاتالوگ با دسترسی مجاز فراهم است.
                  برای طراحی مسیرهای مشتری از شبیه‌ساز Workflow استفاده کنید.
                </p>
              )}
            </>
          ) : (
            <p className="rounded-xl border p-5 text-sm text-muted-foreground">
              یک Action انتخاب کنید.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
