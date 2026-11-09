"use client";

import { GripVertical } from "lucide-react";
import { useRef } from "react";
import { flushSync } from "react-dom";
import { Button } from "@/components/ui/button";

export const orderOperations = "sticky left-0 z-10 border-s bg-card px-2";

const movement = new WeakMap<HTMLElement, Animation>();

function animateMove(list: HTMLElement, apply: () => void) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    apply();
    return;
  }
  const rows = Array.from(list.querySelectorAll<HTMLElement>("[data-order-row]"))
    .filter(row => row.closest("[data-order-list]") === list);
  const before = rows.map(row => row.getBoundingClientRect().top);
  rows.forEach(row => movement.get(row)?.cancel());
  flushSync(apply);
  rows.forEach((row, index) => {
    if (!row.isConnected) return;
    const offset = before[index] - row.getBoundingClientRect().top;
    if (Math.abs(offset) < 1 || typeof row.animate !== "function") return;
    movement.set(row, row.animate(
      [{ transform: `translateY(${offset}px)` }, { transform: "translateY(0)" }],
      { duration: 200, easing: "cubic-bezier(.2,.7,.2,1)" },
    ));
  });
}

export function OrderHandle({ id, label, ids, move, disabled }: {
  id: string;
  label: string;
  ids: readonly string[];
  move: (from: string, to: string) => void;
  disabled?: boolean;
}) {
  const drag = useRef<{ source: HTMLElement; target?: HTMLElement } | null>(null);
  if (ids.length < 2 || !ids.includes(id)) return null;

  function dropTarget(handle: HTMLElement, x: number, y: number) {
    const row = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-order-row]");
    const target = row?.dataset.orderRow;
    if (!row || !target || target === id || !ids.includes(target) ||
        row.closest("[data-order-list]") !== handle.closest("[data-order-list]")) return;
    return row;
  }

  function clearDrag() {
    drag.current?.source.removeAttribute("data-order-dragging");
    drag.current?.target?.removeAttribute("data-order-target");
    drag.current = null;
  }

  function commit(handle: HTMLElement, next: string) {
    const list = handle.closest<HTMLElement>("[data-order-list]");
    if (!list) return;
    animateMove(list, () => move(id, next));
    handle.focus({ preventScroll: true });
  }

  return <Button type="button" variant="ghost" size="icon" disabled={disabled}
    className="size-8 touch-none cursor-grab text-muted-foreground active:cursor-grabbing"
    aria-label={`تغییر ترتیب ${label} با کلیدهای بالا و پایین`} title="تغییر ترتیب"
    onKeyDown={(event) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      event.preventDefault();
      const next = ids[ids.indexOf(id) + (event.key === "ArrowUp" ? -1 : 1)];
      if (next) commit(event.currentTarget, next);
    }}
    onPointerDown={(event) => {
      if (event.button !== 0 || !event.isPrimary) return;
      const source = event.currentTarget.closest<HTMLElement>("[data-order-row]");
      if (!source) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      clearDrag();
      drag.current = { source };
      source.dataset.orderDragging = "";
    }}
    onPointerMove={(event) => {
      if (!drag.current) return;
      const target = dropTarget(event.currentTarget, event.clientX, event.clientY);
      if (target === drag.current.target) return;
      drag.current.target?.removeAttribute("data-order-target");
      if (target) target.dataset.orderTarget = "";
      drag.current.target = target;
    }}
    onPointerUp={(event) => {
      if (!drag.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
      const target = dropTarget(event.currentTarget, event.clientX, event.clientY)?.dataset.orderRow;
      clearDrag();
      if (target) commit(event.currentTarget, target);
    }}
    onPointerCancel={clearDrag}
    onLostPointerCapture={clearDrag}><GripVertical aria-hidden="true" /></Button>;
}
