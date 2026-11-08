"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SectionSearch } from "@/components/blocks/section-search";
import { ReauthenticationForm } from "@/components/blocks/reauthentication";
import { useBotConfigVersion } from "@/components/blocks/bot-config-version";
import { useSectionCommand } from "@/components/runtime/use-section-command";
import { useSectionList } from "@/components/runtime/use-section-list";
import {
  botCatalogQuery, catalogEffectLabels, type BotCatalogRuleList, type CatalogAuditRow,
  type CatalogChange, type CatalogEffect, type CatalogListQuery,
} from "@/lib/bot-catalog-acl";
import { listBotCatalog, listBotCatalogAudit } from "@/lib/bot-catalog-client";
import type { SectionRpcError } from "@/lib/section-rpc";
import { setBotCatalogRules } from "@/app/(console)/bots/[id]/catalog-actions";

const choices: { value: CatalogEffect; label: string }[] = [
  { value: "allow", label: "مجاز" },
  { value: "deny", label: "ممنوع" },
  { value: "inherit", label: "ارث‌بری" },
];
const errors: Record<SectionRpcError, string> = {
  validation: "ورودی‌ها یا ردیف‌های انتخاب‌شده را بررسی کنید.",
  session_expired: "نشست منقضی شده است. دوباره وارد شوید.",
  permission_denied: "حساب فعلی به این عملیات در فروشگاه دسترسی ندارد.",
  store_switch_required: "برای تغییر قوانین، فروشگاه این ربات را از بالای پنل انتخاب کنید.",
  reauthentication_required: "برای اعمال قانون، هویت خود را در همین بخش تأیید کنید.",
  conflict: "نسخهٔ تنظیمات تغییر کرده است. وضعیت تازه را بخوانید و انتخاب را بررسی کنید.",
  unavailable: "فهرست دریافت نشد. دوباره تلاش کنید.",
  outcome_unknown: "نتیجهٔ ذخیره مشخص نیست. پیش از تلاش دوباره، وضعیت و تاریخچهٔ قوانین را بررسی کنید.",
};
const count = new Intl.NumberFormat("fa-IR");
const date = new Intl.DateTimeFormat("fa-IR", { dateStyle: "short", timeStyle: "medium", timeZone: "Asia/Tehran" });

export function BotCatalogAccessPanel({ botId, initialData, initialQuery, initialAudit }: {
  botId: string;
  initialData: BotCatalogRuleList;
  initialQuery: CatalogListQuery;
  initialAudit: CatalogAuditRow[];
}) {
  const { advance } = useBotConfigVersion();
  const read = useCallback((query: CatalogListQuery, signal: AbortSignal) =>
    listBotCatalog(botId, query, signal), [botId]);
  const list = useSectionList(botCatalogQuery, initialQuery, initialData, read);
  const { data, key, query, pending, error, navigate, reload } = list;
  const command = useSectionCommand((input: CatalogChange) => setBotCatalogRules(botId, input));
  const [selection, setSelection] = useState<{ key: string; ids: number[] }>({ key, ids: [] });
  const [effect, setEffect] = useState<CatalogEffect>("allow");
  const [proof, setProof] = useState<{ pathname: string; key: string; input: CatalogChange } | null>(null);
  const [audit, setAudit] = useState(initialAudit);
  const [auditFailed, setAuditFailed] = useState(false);
  const auditRead = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const category = query.kind === "category";
  const activeProof = proof?.key === key ? proof : null;
  const locked = command.pending || activeProof !== null;
  const selected = selection.key === key
    ? data.items.filter(row => selection.ids.includes(row.id)).map(row => row.id) : [];
  const maxPage = Math.min(100_000, Math.max(1, Math.ceil(data.total / data.page_size)));
  const rejected = command.result?.ok === false ? command.result.code : null;
  const needsReadback = rejected === "conflict" || rejected === "outcome_unknown";

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      auditRead.current?.abort();
    };
  }, []);

  useEffect(() => {
    // A rule change can remove the final row from a filtered page.
    if (!pending && !error && query.page > maxPage) navigate({ ...query, page: maxPage }, true);
  }, [error, maxPage, navigate, pending, query]);

  async function refreshAudit() {
    auditRead.current?.abort();
    const controller = new AbortController();
    auditRead.current = controller;
    const result = await listBotCatalogAudit(botId, controller.signal);
    if (controller.signal.aborted) return;
    setAuditFailed(!result.ok);
    if (result.ok) setAudit(result.data.items);
  }

  function changeQuery(next: CatalogListQuery) {
    if (botCatalogQuery.write(next).toString() === key) return;
    setSelection({ key, ids: [] });
    setProof(null);
    if (!needsReadback) command.clear();
    navigate(next);
  }

  async function apply(input: CatalogChange, queryKey: string, verified = false) {
    const pathname = window.location.pathname;
    const result = await command.run(input);
    if (!result || !mounted.current || window.location.pathname !== pathname) return;
    if (result.ok) {
      advance(input.expected_version, result.data.version);
      setSelection({ key: queryKey, ids: [] });
      reload();
      if (result.data.changed > 0) void refreshAudit();
    } else if (result.code === "reauthentication_required" && !verified) {
      setProof({ pathname, key: queryKey, input });
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (locked || pending || error || needsReadback || !selected.length || !data.policy_ready) return;
    void apply({ kind: query.kind, effect, expected_version: data.version, target_ids: selected }, key);
  }

  return <>
    <Card id="catalog-access" className="scroll-mt-24">
      <CardHeader><CardTitle>دسترسی محصولات و دسته‌بندی‌ها به این ربات</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-2" aria-label="نوع فهرست">
            <Button type="button" size="sm" disabled={locked} aria-pressed={!category}
              variant={category ? "outline" : "default"}
              onClick={() => changeQuery({ ...query, kind: "product", page: 1 })}>محصولات</Button>
            <Button type="button" size="sm" disabled={locked} aria-pressed={category}
              variant={category ? "default" : "outline"}
              onClick={() => changeQuery({ ...query, kind: "category", page: 1 })}>دسته‌بندی‌ها</Button>
          </div>
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">راهنمای قوانین</summary>
            <p className="mt-2 leading-6">
              قانون صریح محصول، سپس قانون دسته‌بندی و در پایان پیش‌فرض ربات اعمال می‌شود.
              پیش‌فرض این ربات <strong>{catalogEffectLabels[data.default_effect]}</strong> است.
            </p>
          </details>
        </div>
        <SectionSearch field={category ? "نام دسته‌بندی" : "نام محصول"} value={query.q}
          filter={query.effect} choices={choices} disabled={locked}
          onSearch={q => changeQuery({ ...query, q, page: 1 })}
          onFilter={effect => changeQuery({ ...query, effect, page: 1 })} />

        <div className="flex min-h-8 flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <p role="status">{pending ? "در حال دریافت فهرست…" : error ? "" : `${count.format(data.total)} مورد`}</p>
          <nav aria-label="صفحه‌بندی قوانین ربات" className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" disabled={locked || pending || !!error || query.page <= 1}
              onClick={() => changeQuery({ ...query, page: query.page - 1 })}>قبلی</Button>
            <span>صفحهٔ {count.format(query.page)} از {count.format(Math.max(query.page, maxPage))}</span>
            <Button type="button" variant="outline" size="sm" disabled={locked || pending || !!error || query.page >= maxPage}
              onClick={() => changeQuery({ ...query, page: query.page + 1 })}>بعدی</Button>
          </nav>
        </div>

        {error ? <div className="flex flex-wrap items-center gap-2 text-sm">
          <p role="alert" className="text-destructive">{errors[error]}</p>
          <Button type="button" size="sm" variant="outline" onClick={reload}>تلاش دوباره</Button>
        </div> : null}
        <form onSubmit={save} className="space-y-3">
          <div aria-busy={pending} className="max-h-[420px] overflow-auto rounded-lg border">
            <fieldset disabled={locked || pending || !!error} className={pending ? "opacity-60" : undefined}>
              {data.items.map(item => <label key={item.id}
                className="flex cursor-pointer flex-wrap items-center gap-3 border-b px-3 py-2 text-sm last:border-b-0 hover:bg-muted/40">
                <input type="checkbox" checked={selected.includes(item.id)} className="size-4 accent-primary"
                  onChange={event => {
                    const checked = event.target.checked;
                    setSelection({ key, ids: checked ? [...selected, item.id] : selected.filter(id => id !== item.id) });
                  }} />
                <span className="min-w-32 flex-1 font-medium">{item.name}</span>
                <span className="text-xs text-muted-foreground">{catalogEffectLabels[item.effect]}</span>
                {!category && data.kind === "product" ? <span className="text-xs text-muted-foreground">
                  {item.effective_access ? "قابل نمایش" : "غیرقابل نمایش"}
                </span> : null}
                {!item.is_published ? <span className="text-xs text-muted-foreground">منتشرنشده</span> : null}
              </label>)}
              {!data.items.length && !pending && !error ? <p className="p-6 text-center text-sm text-muted-foreground">
                {query.q || query.effect ? "موردی با این فیلترها پیدا نشد." :
                  category ? "هنوز دسته‌بندی ثبت نشده است." : "هنوز محصولی ثبت نشده است."}
              </p> : null}
            </fieldset>
          </div>
          {!data.policy_ready && !pending ? <p className="text-xs text-muted-foreground">کاتالوگ این فروشگاه هنوز آماده نیست.</p> : null}
          <div className="flex flex-wrap items-center gap-2">
            <p className="me-auto text-xs text-muted-foreground">{count.format(selected.length)} انتخاب‌شده</p>
            <select aria-label="قانون انتخاب‌شده‌ها" value={effect}
              onChange={event => setEffect(event.target.value as CatalogEffect)}
              disabled={locked || pending || !!error || !selected.length}
              className="h-9 rounded-md border bg-background px-3 text-sm">
              <option value="allow">مجاز</option>
              <option value="deny">ممنوع</option>
              <option value="inherit">ارث‌بری از قوانین کاتالوگ</option>
            </select>
            <Button type="submit" size="sm"
              disabled={locked || pending || !!error || needsReadback || !data.policy_ready || !selected.length}>
              {command.pending ? "در حال ذخیره…" : "اعمال قانون"}
            </Button>
          </div>
        </form>

        {command.result?.ok ? <p role="status" className="text-sm">
          {command.result.data.changed
            ? `قانون ${count.format(command.result.data.changed)} مورد ذخیره شد.`
            : "قانون موارد انتخاب‌شده از قبل همین مقدار بود."}
        </p> : null}
        {rejected && !activeProof ? <p role="alert" className="text-sm text-destructive">{errors[rejected]}</p> : null}
        {needsReadback ? <Button type="button" size="sm" variant="outline" disabled={pending} onClick={() => {
          command.clear();
          reload();
          void refreshAudit();
        }}>خواندن وضعیت تازه</Button> : null}
        {activeProof ? <div className="rounded-lg border p-4">
          <ReauthenticationForm onCancel={() => { setProof(null); command.clear(); }}
            onVerified={async () => {
              if (!mounted.current || window.location.pathname !== activeProof.pathname) return;
              setProof(null);
              const current = botCatalogQuery.read(new URL(window.location.href).searchParams);
              if (botCatalogQuery.write(current).toString() !== activeProof.key) {
                command.clear();
                return;
              }
              await apply(activeProof.input, activeProof.key, true);
            }} />
        </div> : null}
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>تاریخچهٔ قوانین دسترسی</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {auditFailed ? <div className="flex flex-wrap items-center gap-2 text-xs">
          <p role="status">تاریخچه به‌روز نشد.</p>
          <Button type="button" size="sm" variant="outline" onClick={() => void refreshAudit()}>تلاش دوباره</Button>
        </div> : null}
        {audit.slice(0, 12).map((row, index) =>
          <div key={`${row.object_type}-${row.object_id}-${row.created_at}-${index}`}
            className="flex flex-wrap justify-between gap-2 border-b py-2 text-xs">
            <span>{row.object_type === "product" ? "محصول" : "دسته‌بندی"} #{row.object_id}
              {" · "}{catalogEffectLabels[row.old_effect]} ← {catalogEffectLabels[row.new_effect]}</span>
            <span className="text-muted-foreground">
              مدیر {count.format(row.actor_id)}{row.created_at ? ` · ${date.format(new Date(row.created_at))}` : ""}
            </span>
          </div>)}
        {!audit.length ? <p className="text-sm text-muted-foreground">هنوز تغییر مستقیمی برای این ربات ثبت نشده است.</p> : null}
      </CardContent>
    </Card>
  </>;
}
