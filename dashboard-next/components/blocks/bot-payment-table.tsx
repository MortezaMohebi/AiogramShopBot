"use client";

import { PasswordActionForm } from "@/components/blocks/password-action-form";

import { useMemo, useState } from "react";
import Link from "next/link";
import { setBotPaymentAccess } from "@/app/(console)/bots/[id]/commerce-actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LocalRelationPicker } from "@/components/ui/local-relation-picker";
import { orderOperations } from "@/components/ui/order-handle";
import type { BotPaymentAccount } from "@/lib/store-commerce";

const stateLabels = { draft: "پیش‌نویس", active: "فعال", disabled: "غیرفعال" };

export function BotPaymentTable({ botId, accounts }: {
  botId: string; accounts: BotPaymentAccount[];
}) {
  const [editing, setEditing] = useState<string>();
  const account = accounts.find((item) => item.id === editing);
  const [adding, setAdding] = useState(false);
  const rows = accounts.filter((item) => item.granted || item.id === editing);
  const choices = useMemo(() => accounts.map((item) => ({
    id: item.id, label: item.name, detail: `${stateLabels[item.state]} · ${item.currency}`,
  })), [accounts]);

  return <div className="space-y-3">
    <div className="flex flex-wrap items-center gap-2">
      <p className="me-auto font-semibold">حساب‌های پرداخت این ربات</p>
      {accounts.length > 0 && <LocalRelationPicker label="انتخاب حساب پرداخت" items={choices}
        onSelect={({ id }) => {
          setAdding(!accounts.find((item) => item.id === id)?.granted);
          setEditing(id);
        }} />}
      <Button asChild variant="outline" size="sm"><Link href="/payment-accounts">مدیریت حساب‌ها</Link></Button>
    </div>
    {rows.length ? <div className="overflow-x-auto rounded-md border">
      <table className="w-full min-w-96 text-sm">
        <thead className="bg-muted"><tr>
          <th scope="col" className="p-2 text-start">حساب</th><th scope="col" className="p-2 text-start">دسترسی</th>
          <th scope="col" className="p-2 text-start">اولویت</th><th scope="col" className={orderOperations}>عملیات</th>
        </tr></thead>
        <tbody>{rows.map((item) => <tr key={item.id} className="border-t">
          <td className="p-2"><bdi>{item.name}</bdi><small className="ms-1 text-muted-foreground">{stateLabels[item.state]} · {item.currency}</small></td>
          <td className="p-2">{item.granted ? "مجاز" : "غیرفعال"}</td>
          <td className="p-2">{item.priority.toLocaleString("fa-IR")}</td>
          <td className={orderOperations}><Button type="button" variant="ghost" size="sm" aria-expanded={editing === item.id}
            onClick={() => { setAdding(false); setEditing(editing === item.id ? undefined : item.id); }}>ویرایش</Button></td>
        </tr>)}</tbody>
      </table>
    </div> : <p className="text-muted-foreground">هنوز حساب پرداختی برای این ربات مجاز نشده است.</p>}
    {account && <PasswordActionForm key={account.id + String(adding)} action={setBotPaymentAccess} className="space-y-3 rounded-md border p-3">
      <p className="font-medium">دسترسی حساب <bdi>{account.name}</bdi></p>
      <input type="hidden" name="bot_id" value={botId} />
      <input type="hidden" name="account_id" value={account.id} />
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block">دسترسی
          <select name="enabled" defaultValue={String(account.granted || (adding && account.state === "active"))}
            className="block h-9 w-full rounded-md border bg-background px-2">
            <option value="false">غیرفعال</option>
            {(account.state === "active" || account.granted) && <option value="true">مجاز</option>}
          </select>
        </label>
        <label className="block">اولویت<Input name="priority" type="number" min={1} max={1000} defaultValue={account.priority} required /></label>
      </div>
      {account.state !== "active" && <p className="text-xs text-muted-foreground">برای اعطای دسترسی، حساب پرداخت باید فعال باشد.</p>}
      <div className="flex gap-2">
        <Button type="submit" size="sm">ذخیرهٔ دسترسی حساب</Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(undefined)}>انصراف</Button>
      </div>
    </PasswordActionForm>}
  </div>;
}
