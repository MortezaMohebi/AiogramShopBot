"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, Select } from "@/components/workflows/fields";
import { workflowRequest } from "@/lib/workflows/client";
import { runtimeRequest, runtimeErrorText } from "@/lib/runtime/client";
import { publicationCanActivate, validBindingChoices } from "@/lib/runtime/state";
import type { Binding, BindingSpec, Publication, PublicationPreview, PublicationBindingPointer, PublishSource, Page } from "@/lib/runtime/types";
import type { BotChoice, Diff, WorkflowList, WorkflowRecord } from "@/lib/workflows/types";
import { RuntimeDate, RuntimeEmpty, RuntimeId, RuntimePanel } from "./shared";
import { RuntimeMutationNotice, useRuntimeMutation } from "./use-mutation";
import { RetirePublication } from "./operations";
function bindingKey(botId: string, kind: string, key: string) {
  return `${botId}:${kind}:${key}`;
}
function BindingSummary({
  items
}: {
  items: BindingSpec[];
}) {
  return <div className="space-y-2">
  {items.map((item, index) => <div key={index} className="min-w-0 rounded border p-3 text-xs leading-6">
    <p>ربات <RuntimeId>{item.bot_id}</RuntimeId></p>
    <p>
      <RuntimeId>
        {`${item.kind}:${item.key} → ${item.node_id}`}
      </RuntimeId>
    </p>
    <p>اولویت {item.priority} · {item.enabled ? "فعال" : "غیرفعال"} · {item.eligibility === "all" ? "همهٔ مشتریان" : "مشتری موجود"} · جایگزین {item.fallback === "legacy" ? "مسیر قبلی ربات" : "بدون پاسخ"}</p>
  </div>)}
</div>;
}
/** Selected changes and retained pointers are different sets; neither implies deletion. */
function BindingPointerSummary({ items }: { items: PublicationBindingPointer[] }) {
  return <div className="space-y-2">{items.map(binding => <div key={binding.id} className="min-w-0 rounded border p-3 text-xs leading-6">
    <p>ربات <RuntimeId>{binding.bot_id}</RuntimeId></p>
    <p><RuntimeId>{`${binding.kind}:${binding.key} → ${binding.node_id}`}</RuntimeId></p>
    <p>انتشار <RuntimeId>{binding.publication_id}</RuntimeId></p>
    <p>نسخهٔ اتصال {binding.version} · {binding.enabled ? "فعال" : "غیرفعال"}</p>
  </div>)}</div>;
}
type Comparison = NonNullable<PublicationPreview["diff"]["binding_comparisons"]>[number];

/** Load detail only when requested, once per distinct selected before/after pair. */
function ComparisonGroup({ items, workflowId, next }: { items: Comparison[]; workflowId: string; next: number }) {
  const [detail, setDetail] = useState<Diff | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const baseline = items[0];
  async function load() {
    if (busy || !baseline.previous_revision) return;
    setBusy(true);
    setError("");
    try {
      setDetail(await workflowRequest<Diff>(`/${workflowId}/compare?left=${baseline.previous_revision}&right=${next}`));
    } catch (cause) {
      setError(runtimeErrorText(cause));
    } finally {
      setBusy(false);
    }
  }
  return <div className="space-y-2 rounded border p-3 text-xs leading-6">
    <h4 className="font-semibold">{baseline.previous_revision === null ? `اتصال تازه به نسخهٔ ${next}` : `مقایسهٔ نسخهٔ ${baseline.previous_revision} با ${next}`}</h4>
    <p>{baseline.previous_revision === null ? "این ورودی‌ها اتصال قبلی ندارند." : baseline.definition_changed ? "تعریف تغییر کرده است." : "تعریف تغییری ندارد."}</p>
    <ul>{items.map(item => <li key={bindingKey(item.bot_id,item.kind,item.key)}><RuntimeId>{`${item.bot_id} · ${item.kind}:${item.key}`}</RuntimeId></li>)}</ul>
    {baseline.previous_revision !== null && baseline.definition_changed && !detail && <Button type="button" disabled={busy} onClick={() => void load()}>مشاهدهٔ تغییرهای تعریف</Button>}
    {error && <p role="alert">{error}</p>}
    {detail && (["nodes", "edges", "variables"] as const).map(key => <p key={key}><bdi>{key}</bdi>: {detail[key].added.length} افزوده · {detail[key].removed.length} حذف · {detail[key].changed.length} تغییر</p>)}
  </div>;
}

function DefinitionComparisons({ preview, workflowId }: { preview: PublicationPreview; workflowId: string }) {
  const groups = new Map<number | null, Comparison[]>();
  for (const item of preview.diff.binding_comparisons ?? []) {
    const group = groups.get(item.previous_revision) ?? [];
    group.push(item);
    groups.set(item.previous_revision, group);
  }
  return <div className="space-y-2">
    {[...groups].map(([revision, items]) => <ComparisonGroup key={revision ?? "unbound"} items={items} workflowId={workflowId} next={preview.diff.next_revision} />)}
    {!groups.size && <p className="text-xs">این پیش‌نمایش مقایسهٔ نسخه برای هر ورودی ندارد.</p>}
  </div>;
}
/** Only exact declared entries and explicit Bot choices can enter a publication request. */
function ReviewForm({
  source,
  bots,
  bindings,
  canPublish,
  rollback
}: {
  source: PublishSource;
  bots: BotChoice[];
  bindings: Binding[];
  canPublish: boolean;
  rollback: boolean;
}) {
  const choices = validBindingChoices(source.definition, bots);
  const [selected, setSelected] = useState<Record<string, BindingSpec>>(() => rollback ? Object.fromEntries(bindings.filter(binding => binding.workflow_id === source.id && choices.some(choice => binding.bot_id === choice.bot.id && binding.kind === choice.entry.kind && binding.key === choice.entry.key && binding.node_id === choice.entry.node_id)).map(binding => [bindingKey(binding.bot_id, binding.kind, binding.key), {
    bot_id: binding.bot_id,
    kind: binding.kind,
    key: binding.key,
    node_id: binding.node_id,
    priority: binding.priority,
    enabled: binding.enabled,
    eligibility: binding.eligibility,
    fallback: binding.fallback,
    version_policy: "active_publication"
  }])) : {});
  const [preview, setPreview] = useState<PublicationPreview | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [approved, setApproved] = useState(false),
    [now, setNow] = useState(0);
  const mutation = useRuntimeMutation(),
    generation = useRef(0),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!preview) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [preview]);
  const entries = Object.values(selected),
    locked = busy || mutation.disabled;
  function update(key: string, patch: Partial<BindingSpec>) {
    setSelected(old => ({
      ...old,
      [key]: {
        ...old[key],
        ...patch
      }
    }));
    setPreview(null);
    setApproved(false);
    generation.current++;
  }
  async function createPreview() {
    if (busy || !entries.length) return;
    setBusy(true);
    setError("");
    setPreview(null);
    setApproved(false);
    const token = ++generation.current;
    try {
      const result = await runtimeRequest<PublicationPreview>("/publications/preview", "POST", {
        workflow_id: source.id,
        revision: source.revision,
        bindings: entries
      });
      if (alive.current && token === generation.current) {
        setPreview(result);
        setNow(Date.now());
      }
    } catch (error) {
      if (alive.current && token === generation.current) setError(runtimeErrorText(error));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  return <RuntimePanel title={`${rollback ? "بازگشت برای اجراهای جدید" : "انتشار نسخهٔ ذخیره‌شده"} · ${source.name} · r${source.revision}`}>
  <p className="text-sm leading-7">
    {rollback ? "این نسخهٔ قبلی دوباره برای اجراهای جدید انتخاب می‌شود. اجراهای قبلی جابه‌جا نمی‌شوند." : "یک ورودی و ربات را انتخاب کنید؛ سپس تغییرها را در پیش‌نمایش بررسی کنید. پیش‌نویس ذخیره‌نشده وارد انتشار نمی‌شود."}
  </p>
  <p className="text-xs text-muted-foreground">پلتفرم‌های نسخه: <bdi>
      {source.definition.target_platforms.join(" / ")}
    </bdi></p>
  <fieldset disabled={locked || !canPublish} className="space-y-3 disabled:opacity-60">
    <legend className="mb-3 text-sm font-semibold">ورودی‌های اعلام‌شدهٔ فرایند</legend>
    {choices.map(({
        bot,
        entry
      }) => {
        const key = bindingKey(bot.id, entry.kind, entry.key),
          chosen = selected[key];
        return <div key={key} className="min-w-0 space-y-3 rounded-lg border p-3">
      <label className="flex items-start gap-3 text-sm">
        <input className="mt-1" type="checkbox" checked={!!chosen} disabled={locked || !chosen && entries.length >= 40} onChange={e => {
              setSelected(old => {
                const next = {
                  ...old
                };
                if (e.target.checked) next[key] = {
                  bot_id: bot.id,
                  kind: entry.kind,
                  key: entry.key,
                  node_id: entry.node_id,
                  priority: 0,
                  enabled: true,
                  eligibility: "all",
                  fallback: "legacy",
                  version_policy: "active_publication"
                };else delete next[key];
                return next;
              });
              setPreview(null);
              setApproved(false);
                        generation.current++;
            }} />
        <span className="min-w-0">
          <span>{bot.name} · <bdi>
              {bot.platform}
            </bdi></span>
          <span className="mt-1 block">
            <RuntimeId>
              {`${entry.kind}:${entry.key} → ${entry.node_id}`}
            </RuntimeId>
          </span>
        </span>
      </label>
      {chosen && <div className="grid gap-3 sm:grid-cols-2">
        <Field label="اولویت ورودی">
          <Input aria-label={`اولویت ${entry.key} در ${bot.name}`} type="number" dir="ltr" min={0} max={100} value={chosen.priority} onChange={e => update(key, {
                priority: Number(e.target.value)
              })} />
        </Field>
        <Field label="مخاطب مجاز">
          <Select label={`مخاطب ${entry.key} در ${bot.name}`} value={chosen.eligibility} options={[{
                value: "all",
                label: "همهٔ مشتریان"
              }, {
                value: "existing_customer",
                label: "مشتری موجود"
              }]} onChange={value => update(key, {
                eligibility: value as BindingSpec["eligibility"]
              })} />
        </Field>
        <Field label="مسیر جایگزین">
          <Select label={`جایگزین ${entry.key} در ${bot.name}`} value={chosen.fallback} options={[{
                value: "legacy",
                label: "مسیر قبلی ربات"
              }, {
                value: "ignore",
                label: "بدون پاسخ"
              }]} onChange={value => update(key, {
                fallback: value as BindingSpec["fallback"]
              })} />
        </Field>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={chosen.enabled} onChange={e => update(key, {
                enabled: e.target.checked
              })} />ورودی فعال باشد</label>
      </div>}
    </div>;
      })}
    {!choices.length && <RuntimeEmpty>ورودی اعلام‌شده و ربات واجد شرایطی برای این نسخه وجود ندارد. تنظیمات و ورودی‌های فرایند را بررسی کنید.</RuntimeEmpty>}
    <Button type="button" variant={preview ? "outline" : "default"} disabled={!entries.length || locked || !canPublish} onClick={() => void createPreview()}>
      {busy ? "در حال بررسی انتشار…" : "ساخت پیش‌نمایش انتشار"}
    </Button>
  </fieldset>
  {error && <p role="alert" className="text-sm text-destructive">
    {error}
  </p>}
  {preview && <section className="space-y-5 rounded-lg border border-primary/30 bg-primary/5 p-4" aria-label="پیش‌نمایش انتشار">
    <div className="space-y-2">
      <h3 className="font-semibold">
        {preview.ready ? "نسخه آمادهٔ بررسی و تأیید است" : "این نسخه آمادهٔ انتشار نیست"}
      </h3>
      <p className="text-xs leading-6">مهلت پیش‌نمایش: <RuntimeDate value={preview.expires_at} /></p>
    </div>
    {preview.issues.length > 0 && <ul className="list-inside list-disc space-y-2 text-sm">
      {preview.issues.map((issue, index) => <li key={index}>{issue.message ?? "مانع انتشار ثبت شده است"} · <RuntimeId>
          {issue.code}
        </RuntimeId>{issue.node_id && <> · گره <RuntimeId>
            {issue.node_id}
          </RuntimeId></>}</li>)}
    </ul>}
    <DefinitionComparisons key={preview.preview_id} preview={preview} workflowId={source.id} />
    <div className="grid min-w-0 gap-4 md:grid-cols-2">
      <div className="space-y-2">
        <h4 className="text-sm font-semibold">ورودی‌های فعلی ربات‌های انتخابی</h4>
        {preview.diff.previous_bindings.length
          ? <BindingPointerSummary items={preview.diff.previous_bindings} />
          : <p className="text-xs text-muted-foreground">اتصال فعلی ندارد.</p>}
      </div>
      <div className="space-y-2">
        <h4 className="text-sm font-semibold">ورودی‌های انتخاب‌شده برای تغییر</h4>
        <BindingSummary items={preview.diff.next_bindings} />
      </div>
    </div>
    <div className="space-y-3 rounded-lg border p-3">
      <h4 className="text-sm font-semibold">ورودی‌های انتخاب‌نشده که حفظ می‌شوند</h4>
      <p className="text-xs leading-6">ورودی‌های انتخاب‌نشده حذف یا غیرفعال نمی‌شوند. ورودی‌های ربات‌های دیگر هم بدون تغییر باقی می‌مانند.</p>
      {preview.diff.unchanged_bindings.length
        ? <BindingPointerSummary items={preview.diff.unchanged_bindings} />
        : <p className="text-xs text-muted-foreground">ورودی دیگری در ربات‌های انتخابی این پیش‌نمایش ثبت نشده است.</p>}
    </div>
    <div className="space-y-3">
      <h4 className="text-sm font-semibold">وابستگی‌ها و اثر جانبی</h4>
      {preview.dependencies.map(dep => <div key={dep.node_id} className="rounded border p-3 text-xs leading-6">
        <RuntimeId>
          {`${dep.key}@${dep.version}`}
        </RuntimeId>
        <p>گره <RuntimeId>
            {dep.node_id}
          </RuntimeId> · اثر <RuntimeId>
            {dep.side_effect}
          </RuntimeId> · تأیید <RuntimeId>
            {dep.confirmation}
          </RuntimeId></p>
      </div>)}
      {!!preview.dependencies.length && <p className="text-xs leading-6">در اجرای واقعی، تلاش مجدد و انتظار برای تأیید روی همان عملیات می‌مانند. این دو خروجی در شبیه‌ساز نمایش داده می‌شوند؛ برای انتشار، مقصدشان باید با مسیر خطا یکی باشد.</p>}
      {!preview.dependencies.length && <p className="text-xs text-muted-foreground">این نسخه Action ندارد.</p>}
      <p className="text-xs leading-6">گره دارای اثر تغییر داده: {preview.mutating_nodes.length.toLocaleString("fa-IR")} · پلتفرم‌ها: <bdi>
          {preview.platforms.join(" / ")}
        </bdi></p>
    </div>
    <p className="text-sm leading-7">فعال‌سازی فقط ورودی‌های بازبینی‌شده را برای اجراهای جدید تغییر می‌دهد. مجوز فروشگاه و ربات و تنظیم سراسری جداگانه اعمال می‌شوند. تأیید تازهٔ رمز و MFA لازم است.</p>
    <label className="flex items-start gap-2 text-sm leading-7"><input className="mt-2" type="checkbox" checked={approved} disabled={!preview.ready || mutation.disabled || Date.parse(preview.expires_at) <= now} onChange={e => setApproved(e.target.checked)} />نسخه، ربات‌ها، تغییرهای انتخاب‌شده، ورودی‌های حفظ‌شده و اثر جانبی را بررسی و فعال‌سازی همین پیش‌نمایش را تأیید می‌کنم.</label>
    {Date.parse(preview.expires_at) <= now && <p role="status" className="text-sm text-destructive">مهلت پیش‌نمایش پایان یافته است؛ پیش‌نمایش تازه بسازید.</p>}
    <Button type="button" disabled={mutation.disabled || !publicationCanActivate(preview, approved, canPublish, now)} onClick={() => void mutation.execute("/publications/activate", {
        preview_id: preview.preview_id,
        approved: true
      }, "ورودی‌های نسخهٔ بررسی‌شده فعال شدند. وضعیت مجوز اجرا را نیز بررسی کنید.", {
        previewId: preview.preview_id,
        revision: preview.diff.next_revision
      })}>تأیید و فعال‌سازی همین پیش‌نمایش</Button>
    <RuntimeMutationNotice mutation={mutation} />
  </section>}
</RuntimePanel>;
}
export function RuntimePublications({
  publications,
  bindings,
  workflows: initialWorkflows,
  bots: initialBots,
  canPublish
}: {
  publications: Page<Publication>;
  bindings: Page<Binding>;
  workflows: WorkflowList;
  bots: Page<BotChoice>;
  canPublish: boolean;
}) {
  const [workflows, setWorkflows] = useState(initialWorkflows),
    [bots, setBots] = useState(initialBots),
    [workflowId, setWorkflowId] = useState(""),
    [revision, setRevision] = useState(""),
    [query, setQuery] = useState(""),
    [source, setSource] = useState<PublishSource | null>(null),
    [rollback, setRollback] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const generation = useRef(0),
    active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function loadSource(id: string, rev?: number, back = false) {
    const token = ++generation.current;
    setBusy(true);
    setError("");
    setSource(null);
    setWorkflowId(id);
    setRevision(rev ? String(rev) : "");
    setRollback(back);
    try {
      const record = await workflowRequest<WorkflowRecord>(`/${id}${rev ? `/revisions/${rev}` : ""}`);
      if (active.current && token === generation.current) {
        setSource(record);
        setRevision(String(record.revision));
      }
    } catch (error) {
      if (active.current && token === generation.current) setError(runtimeErrorText(error));
    } finally {
      if (active.current && token === generation.current) setBusy(false);
    }
  }
  async function loadChoices(kind: "workflows" | "bots", more = false) {
    setBusy(true);
    setError("");
    try {
      if (kind === "workflows") {
        const next = await workflowRequest<WorkflowList>(`?status=draft&q=${encodeURIComponent(query)}&page=${more ? workflows.page + 1 : 1}`);
        if (active.current) setWorkflows(old => ({
          ...next,
          items: more ? [...old.items, ...next.items] : next.items
        }));
      } else {
        const next = await workflowRequest<Page<BotChoice>>(`/bots?page=${bots.page + 1}`);
        if (active.current) setBots(old => ({
          ...next,
          items: [...old.items, ...next.items]
        }));
      }
    } catch (error) {
      if (active.current) setError(runtimeErrorText(error));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return <div className="space-y-5">
  {!canPublish && <p className="rounded-lg border p-3 text-sm leading-7 text-muted-foreground">دسترسی این حساب برای مشاهده است؛ انتشار و بازگشت به مجوز انتشار در فروشگاه نیاز دارند.</p>}
  {canPublish && <RuntimePanel title="انتخاب نسخه برای انتشار">
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-0 flex-1 space-y-2 text-xs">
        <span>جستجوی فرایند</span>
        <Input maxLength={100} value={query} onChange={e => setQuery(e.target.value)} />
      </label>
      <Button type="button" variant="outline" disabled={busy} onClick={() => void loadChoices("workflows")}>جستجو</Button>
    </div>
    <Field label="فرایند ذخیره‌شده">
      <Select label="فرایند برای انتشار" value={workflowId} disabled={busy} onChange={id => {
          if (id) void loadSource(id);else {
            generation.current++;
            setWorkflowId("");
            setSource(null);
          }
        }} options={[{
          value: "",
          label: "انتخاب فرایند"
        }, ...workflows.items.map(item => ({
          value: item.id,
          label: `${item.name} · r${item.revision}`
        })), ...(source && !workflows.items.some(item => item.id === source.id) ? [{
          value: source.id,
          label: source.name
        }] : [])]} />
    </Field>
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-0 max-w-full space-y-2 text-xs">
        <span>شمارهٔ نسخهٔ ذخیره‌شده</span>
        <Input aria-label="شماره نسخه برای انتشار" disabled={busy} dir="ltr" type="number" min={1} value={revision} onChange={e => {
            setRevision(e.target.value);
            setSource(null);
            generation.current++;
          }} />
      </label>
      <Button type="button" variant="outline" disabled={busy || !workflowId || !/^\d+$/.test(revision) || Number(revision) < 1} onClick={() => void loadSource(workflowId, Number(revision))}>دریافت این نسخه</Button>
      {workflows.has_more && <Button type="button" variant="outline" disabled={busy} onClick={() => void loadChoices("workflows", true)}>فرایندهای بیشتر</Button>}
      {bots.has_more && <Button type="button" variant="outline" disabled={busy} onClick={() => void loadChoices("bots")}>ربات‌های بیشتر</Button>}
    </div>
    <p role="status" className="text-xs text-muted-foreground">
      {busy ? "در حال دریافت نسخه و انتخاب‌ها…" : "فقط نسخهٔ ذخیره‌شده و ورودی اعلام‌شده قابل انتشار است."}
    </p>
    {error && <p role="alert" className="text-sm text-destructive">
      {error}
    </p>}
  </RuntimePanel>}
  {source && canPublish && <ReviewForm key={`${source.id}-${source.revision}-${rollback}`} source={source} bots={bots.items} bindings={bindings.items} canPublish={canPublish} rollback={rollback} />}
  <RuntimePanel title="نسخه‌های منتشرشده">
    <p className="text-sm leading-7 text-muted-foreground">بازگشت یک پیش‌نمایش تازه از نسخهٔ قبلی می‌سازد و تأیید جدا می‌خواهد. اجراهای قبلی به نسخهٔ شروع خود متصل می‌مانند.</p>
    {publications.items.map(publication => <article key={publication.id} className="min-w-0 space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">نسخهٔ r{publication.revision}</h3>
        <span className="text-xs">
          {publication.retired ? "بازنشسته" : `${publication.active_bindings.toLocaleString("fa-IR")} ورودی فعال`}
        </span>
      </div>
      <p>
        <RuntimeId>
          {publication.id}
        </RuntimeId>
      </p>
      <p className="text-xs">فرایند <Link className="text-primary underline" href={`/studio/workflows/${publication.workflow_id}`}>
          <RuntimeId>
            {publication.workflow_id}
          </RuntimeId>
        </Link></p>
      <p className="text-xs text-muted-foreground">
        <RuntimeDate value={publication.created_at} />
      </p>
      <details>
        <summary className="cursor-pointer text-xs">اثر انگشت نسخه</summary>
        <p className="mt-2">
          <RuntimeId>
            {publication.digest}
          </RuntimeId>
        </p>
      </details>
      <div className="flex flex-wrap gap-4 text-sm">
        <Link className="text-primary underline" href={`/studio/runtime?tab=runs&publication_id=${publication.id}`}>اجراهای این نسخه</Link>
        {canPublish && !publication.retired && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void loadSource(publication.workflow_id, publication.revision, true)}>بررسی بازگشت به این نسخه</Button>}
      </div>
      <RetirePublication key={`${publication.id}-${publication.retired}`} publication={publication} canPublish={canPublish} />
    </article>)}
    {!publications.items.length && <RuntimeEmpty>نسخهٔ منتشرشده‌ای در این صفحه نیست.</RuntimeEmpty>}
    {bindings.has_more && <p className="text-xs leading-6 text-muted-foreground">فقط صفحهٔ اول اتصال‌ها برای انتخاب بازگشت دریافت شده است. اتصال‌های بیشتر در زبانهٔ «ورودی‌ها» قابل مشاهده‌اند؛ انتخاب نهایی را در پیش‌نمایش بررسی کنید.</p>}
  </RuntimePanel>
</div>;
}
