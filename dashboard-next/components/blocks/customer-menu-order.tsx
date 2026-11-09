"use client";

import { useState } from "react";
import { OrderHandle } from "@/components/ui/order-handle";
import type { CustomerMenuAction, CustomerMenuPolicy } from "@/lib/customer-experience";

export function CustomerMenuOrder({ menu }: { menu: CustomerMenuPolicy }) {
  const [order, setOrder] = useState(() => [...menu.actions,
    ...menu.available_actions.filter(({ key }) => !menu.actions.includes(key)).map(({ key }) => key)]);
  const [enabled, setEnabled] = useState(menu.actions);
  const [notice, setNotice] = useState("");
  const movable = order.filter(key => key === "shop" || enabled.includes(key));
  const labels = new Map(menu.available_actions.map(({ key, label }) => [key, label]));

  function move(from: string, to: string) {
    const start = order.indexOf(from as CustomerMenuAction);
    const end = order.indexOf(to as CustomerMenuAction);
    if (start < 0 || end < 0 || start === end) return;
    const next = [...order];
    next.splice(end, 0, ...next.splice(start, 1));
    setOrder(next);
    setNotice(`${labels.get(next[end])} به جایگاه ${(end + 1).toLocaleString("fa-IR")} منتقل شد.`);
  }

  return <div className="rounded-md border">
    <table data-order-list className="w-full text-sm">
      <thead className="bg-muted"><tr><th scope="col" className="px-2 py-1 text-start">دکمه</th>
        <th scope="col" className="px-2 py-1 text-start">نمایش</th></tr></thead>
      <tbody>{order.map((key, index) => {
        const label = labels.get(key) ?? key;
        const visible = key === "shop" || enabled.includes(key);
        return <tr key={key} data-order-row={key} className="border-t">
          <td><div className="flex items-center gap-1">
            <OrderHandle id={key} label={label} ids={movable} move={move} />{label}
          </div></td>
          <td className="px-2">
            {visible && <><input type="hidden" name="menu_action" value={key} />
              <input type="hidden" name={`order:${key}`} value={index + 1} /></>}
            <input type="checkbox" checked={visible} disabled={key === "shop"} aria-label={`نمایش ${label}`}
              className="accent-primary" onChange={(event) => setEnabled(event.target.checked
                ? [...enabled, key] : enabled.filter((item) => item !== key))} />
          </td>
        </tr>;
      })}</tbody>
    </table>
    <p role="status" className="sr-only">{notice}</p>
  </div>;
}
