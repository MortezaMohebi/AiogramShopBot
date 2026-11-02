import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge RTL-friendly shadcn/Tailwind utility classes consistently. */
export function cn(...classes: ClassValue[]): string {
  return twMerge(clsx(classes));
}

/** Display integral rial amounts without converting them to binary float. */
export function formatIrr(value: string | bigint): string {
  try {
    return `${new Intl.NumberFormat("fa-IR").format(BigInt(value))} ریال`;
  } catch {
    return "—";
  }
}

/** Render human-readable Persian dates using a Jalali display calendar. */
export function formatDate(value?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function statusLabel(value: string): string {
  const names: Record<string, string> = {
    draft: "پیش‌نویس",
    approved: "تأییدشده",
    sending: "در حال ارسال",
    paused: "متوقف",
    needs_review: "نیازمند بررسی",
    completed: "تکمیل‌شده",
    cancelled: "لغوشده",
    pending_review: "در انتظار بررسی",
    approved_unpaid: "تأییدشده، بدون پرداخت",
    pending_payment: "در انتظار پرداخت",
    paid: "پرداخت‌شده",
    paid_unfulfilled: "پرداخت‌شده، نیازمند رسیدگی",
    refunded: "بازپرداخت‌شده",
  };
  return names[value] ?? value;
}
