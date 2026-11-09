"use client";

import { useCallback, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DraftActions } from "@/components/ui/draft-actions";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { RelationTag } from "@/components/ui/relation-tag";
import { SectionSearch } from "@/components/blocks/section-search";
import { ReauthenticationForm } from "@/components/blocks/reauthentication";
import { useSectionCommand } from "@/components/runtime/use-section-command";
import { useSectionList } from "@/components/runtime/use-section-list";
import { readSectionRpc } from "@/lib/section-rpc";
import {
  type ProductBotCatalogList, type ProductBotCatalogCandidate, type ProductBotAssignment, type CatalogEffect,
  catalogEffectLabels, catalogBotLabel, productBotQuery,
} from "@/lib/bot-catalog-acl";
import { setProductBotAccess } from "@/app/(console)/products/[id]/edit/bot-acl-actions";

const errorText = {
  validation: "انتخاب و قانون را بررسی کنید.",
  permission_denied: "اجازهٔ تغییر دسترسی ربات را ندارید.",
  store_switch_required: "فروشگاه مالک محصول را فعال کنید.",
  conflict: "قوانین تغییر کرده‌اند. فهرست را تازه کنید و ربات‌ها را دوباره انتخاب کنید.",
  session_expired: "نشست شما پایان یافته است. دوباره وارد شوید.",
  unavailable: "خواندن فهرست ممکن نشد.",
  outcome_unknown: "نتیجهٔ ذخیره مشخص نیست. فهرست تازه را بررسی کنید.",
  reauthentication_required: "برای ادامه هویت خود را تأیید کنید.",
};

export function ProductBotMany2ManyPanel({ data, query, saved, error }: {
  data: ProductBotCatalogList; query: string; saved: boolean; error: boolean;
}) {
  const read = useCallback((next: { q: string; page: number }, signal: AbortSignal) =>
    readSectionRpc<ProductBotCatalogList>(
      `/api/admin/bot-catalog/products/${data.product_id}?${productBotQuery.write(next)}`, signal,
    ), [data.product_id]);
  const list = useSectionList(productBotQuery, { q: query, page: data.page }, data, read);
  const [selected, setSelected] = useState<ProductBotCatalogCandidate[]>([]);
  const [effect, setEffect] = useState<CatalogEffect>("allow");
  const [proof, setProof] = useState<{ assignments: ProductBotAssignment[]; pathname: string } | null>(null);
  const [proofBusy, setProofBusy] = useState(false);
  const [showLegacy, setShowLegacy] = useState(true);
  const command = useSectionCommand((input: ProductBotAssignment[]) => setProductBotAccess(data.product_id, input));
  const maxPage = Math.max(1, Math.ceil(list.data.total / list.data.page_size));
  const blocked = command.result?.ok === false && ["conflict", "outcome_unknown"].includes(command.result.code);
  const busy = list.pending || command.pending || proof !== null;

  async function apply(assignments: ProductBotAssignment[], verified = false) {
    const pathname = window.location.pathname;
    setShowLegacy(false);
    const result = await command.run(assignments);
    if (result?.ok) {
      setSelected([]);
      list.reload();
    } else if (result?.code === "reauthentication_required" && !verified) {
      setProof({ assignments, pathname });
    }
  }

  function refresh() {
    setSelected([]);
    setShowLegacy(false);
    command.clear();
    list.reload();
  }

  return <Card>
    <CardHeader><CardTitle id="bot-access">دسترسی محصول در ربات‌ها</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      <SectionSearch field="ربات" value={list.query.q} filter={null} choices={[]}
        disabled={busy} onFilter={() => {}} onSearch={(q) => {
          setShowLegacy(false);
          list.navigate({ q, page: 1 });
        }} />
      {showLegacy && saved && <p role="status">دسترسی ربات‌ها ذخیره شد.</p>}
      {showLegacy && error && <p role="alert" className="text-sm text-destructive">ذخیرهٔ قبلی تأیید نشده است.</p>}
      {selected.length > 0 && <div className="flex flex-wrap gap-1.5" aria-label="ربات‌های انتخاب‌شده">
        {selected.map((bot) => <RelationTag key={bot.id} label={`${bot.name} · ${catalogBotLabel(bot.platform)}`}
          disabled={busy} removeLabel={`برداشتن ${bot.name} از انتخاب`}
          onRemove={() => setSelected((previous) => previous.filter((item) => item.id !== bot.id))} />)}
      </div>}
      <div className="overflow-x-auto rounded-md border" aria-busy={list.pending}>
        <table className="w-full min-w-80 text-sm">
          <thead className="bg-muted text-right"><tr><th className="p-2">ربات</th><th className="p-2">قانون فعلی</th></tr></thead>
          <tbody>
            {!list.pending && !list.error && list.data.bots.map((bot) => {
              const chosen = selected.some((item) => item.id === bot.id);
              return <tr key={bot.id} className="border-t">
                <td className="p-2"><label className="flex items-center gap-2">
                  <input type="checkbox" className="accent-primary" checked={chosen}
                    disabled={busy || !!blocked || (!chosen && selected.length >= 100)}
                    onChange={() => setSelected((previous) => chosen ? previous.filter((item) => item.id !== bot.id) : [...previous, bot])} />
                  <span>{bot.name} <small className="text-muted-foreground">{catalogBotLabel(bot.platform)}</small>
                    {bot.status === "draft" && <small className="ms-1 text-muted-foreground">پیش‌نویس</small>}</span>
                </label></td>
                <td className="p-2">{bot.effect === "inherit" ? "ارث‌بری از دسته‌بندی یا پیش‌فرض ربات" : catalogEffectLabels[bot.effect]}</td>
              </tr>;
            })}
            {(list.pending || list.error || !list.data.bots.length) && <tr><td colSpan={2} className="p-4 text-center text-muted-foreground">
              {list.pending ? "در حال دریافت…" : list.error ? errorText[list.error] : "رباتی یافت نشد."}
            </td></tr>}
          </tbody>
        </table>
      </div>
      {(maxPage > 1 || list.query.page > 1) && <nav className="flex items-center gap-2" aria-label="صفحه‌بندی ربات‌ها">
        <Button type="button" size="sm" variant="outline" disabled={busy || list.query.page <= 1}
          onClick={() => list.navigate({ ...list.query, page: list.query.page - 1 })}>قبلی</Button>
        <span className="text-sm">صفحهٔ {list.query.page.toLocaleString("fa-IR")}</span>
        <Button type="button" size="sm" variant="outline" disabled={busy || !!list.error || list.query.page >= maxPage}
          onClick={() => list.navigate({ ...list.query, page: list.query.page + 1 })}>بعدی</Button>
      </nav>}
      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-1 text-sm">قانون انتخاب‌ها
          <select className="block h-9 rounded-md border bg-background px-2" value={effect} disabled={busy}
            onChange={(event) => setEffect(event.target.value as CatalogEffect)}>
            <option value="allow">مجاز</option><option value="deny">ممنوع</option><option value="inherit">ارث‌بری</option>
          </select>
        </label>
        {!blocked && !list.error && <DraftActions dirty={selected.length > 0} pending={command.pending || proof !== null}
          onSave={() => void apply(selected.map(bot => ({ bot_id: bot.id, expected_version: bot.version, effect })))}
          onDiscard={() => { setSelected([]); setEffect("allow"); command.clear(); }} />}
        {(blocked || list.error) && <Button type="button" variant="outline" disabled={busy} onClick={refresh}>تازه‌کردن فهرست</Button>}
      </div>
      {command.result?.ok && <p role="status" className="text-sm">دسترسی ربات‌ها ذخیره شد.</p>}
      {command.result?.ok === false && !proof && <p role="alert" className="text-sm text-destructive">{errorText[command.result.code]}</p>}
      {proof && <Dialog open label="تأیید هویت برای تغییر دسترسی" onClose={() => { if (!proofBusy) setProof(null); }}>
        <div className="p-5"><ReauthenticationForm onBusyChange={setProofBusy} onCancel={() => setProof(null)}
          onVerified={async () => {
            if (window.location.pathname === proof.pathname) await apply(proof.assignments, true);
            setProof(null);
          }} /></div>
      </Dialog>}
    </CardContent>
  </Card>;
}
