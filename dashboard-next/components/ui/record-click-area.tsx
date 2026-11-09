"use client";

import type { MouseEvent, ReactNode } from "react";
import { cn } from "@/lib/utils";

const controls = [
  "a[href]", "button", "input", "select", "textarea", "label", "summary", "form",
  "[contenteditable]:not([contenteditable=false])", "[role=button]", "[role=link]",
  "[role=checkbox]", "[role=menuitem]", "[data-record-ignore]",
].join(", ");

/** Keep table and card semantics; the record's title link owns navigation and focus. */
export function RecordClickArea({
  as: Element, className, children, orderId,
}: {
  as: "tr" | "article" | "section" | "div";
  className?: string;
  orderId?: string;
  children: ReactNode;
}) {
  function openRecord(event: MouseEvent<HTMLElement>) {
    if (event.defaultPrevented || event.button !== 0 ||
        event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
        !(event.target instanceof window.Element)) return;

    const area = event.currentTarget;
    if (event.target.closest("[data-record-area]") !== area) return;
    const control = event.target.closest(controls);
    if (control && area.contains(control)) return;
    const selection = area.ownerDocument.getSelection();
    if (selection && !selection.isCollapsed &&
        (area.contains(selection.anchorNode) || area.contains(selection.focusNode))) return;

    area.querySelector<HTMLElement>("a[data-record-link], button[data-record-trigger]")?.click();
  }

  return <Element
    data-record-area
    data-order-row={orderId}
    className={cn("cursor-pointer hover:bg-muted/45 focus-within:bg-muted/30 motion-safe:transition-colors", className)}
    onClick={openRecord}
  >{children}</Element>;
}
