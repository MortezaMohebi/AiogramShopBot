"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Native modal: contains focus, makes the background inert and restores focus. */
export function Dialog({ open, onClose, label, children, className }: {
  open: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (open && dialog && !dialog.open) dialog.showModal();
    else if (!open && dialog?.open) dialog.close();
    return () => { if (dialog?.open) dialog.close(); };
  }, [open]);

  return <dialog ref={ref} aria-label={label} onCancel={(event) => {
    event.preventDefault();
    onClose();
  }} onClose={onClose} onClick={(event) => {
    if (event.target === event.currentTarget) onClose();
  }} className={cn("m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-y-auto overscroll-contain rounded-xl border border-border bg-popover p-0 text-popover-foreground shadow-xl backdrop:bg-black/60", className)}>
    <div>{children}</div>
  </dialog>;
}
