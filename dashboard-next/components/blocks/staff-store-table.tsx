"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { LocalRelationPicker } from "@/components/ui/local-relation-picker";
import { orderOperations } from "@/components/ui/order-handle";
import type { StaffStorePermissions, StoreAccessLevel } from "@/lib/store-context";

export function StaffStoreTable({ data }: { data: StaffStorePermissions }) {
  const [grants, setGrants] = useState<Record<string, StoreAccessLevel>>(() => Object.fromEntries(
    data.stores.filter((store) => store.granted).map((store) => [store.id, store.access_level ?? "viewer"]),
  ));
  const [defaultId, setDefaultId] = useState(data.default_store_id ?? "");
  const rows = data.stores.filter((store) => Object.hasOwn(grants, store.id));
  const chosenDefault = rows.some((store) => store.id === defaultId) ? defaultId : "";
  const choices = useMemo(() => data.stores.map(({ id, name, slug }) => ({ id, label: name, detail: slug })), [data.stores]);

  return <div className="space-y-2">
    <LocalRelationPicker items={choices} exclude={Object.keys(grants)} label="افزودن فروشگاه"
      onSelect={({ id }) => setGrants((previous) => ({ ...previous, [id]: "viewer" }))} />
    {rows.length ? <div className="overflow-x-auto rounded-md border">
      <table className="w-full min-w-96 text-sm">
        <thead className="bg-muted"><tr>
          <th scope="col" className="p-2 text-start">فروشگاه</th><th scope="col" className="p-2 text-start">سطح دسترسی</th>
          <th scope="col" className="p-2 text-start">پیش‌فرض</th><th scope="col" className={orderOperations}>عملیات</th>
        </tr></thead>
        <tbody>{rows.map((store) => <tr key={store.id} className="border-t">
          <td className="p-2"><input type="hidden" name="store_ids" value={store.id} />
            <bdi>{store.name}</bdi><small className="ms-1 text-muted-foreground"><bdi>{store.slug}</bdi></small>
          </td>
          <td className="p-2"><select name={`access:${store.id}`} value={grants[store.id]}
            aria-label={`سطح دسترسی ${store.name}`} className="h-9 rounded-md border bg-background px-2"
            onChange={(event) => {
              const value = event.target.value as StoreAccessLevel;
              setGrants((previous) => ({ ...previous, [store.id]: value }));
            }}>
            <option value="viewer">مشاهده‌گر</option><option value="editor">ویرایشگر</option><option value="manager">مدیر</option>
          </select></td>
          <td className="p-2"><input type="radio" name="default_store_id" value={store.id} required
            checked={chosenDefault === store.id} onChange={() => setDefaultId(store.id)}
            aria-label={`انتخاب ${store.name} به‌عنوان فروشگاه پیش‌فرض`} /></td>
          <td className={orderOperations}><Button type="button" variant="ghost" size="sm"
            aria-label={`برداشتن دسترسی ${store.name}`} onClick={() => setGrants((previous) => {
              const next = { ...previous };
              delete next[store.id];
              return next;
            })}>برداشتن دسترسی</Button></td>
        </tr>)}</tbody>
      </table>
    </div> : <p role="status" className="text-sm text-muted-foreground">برای ذخیره دست‌کم یک فروشگاه انتخاب کنید.</p>}
  </div>;
}
