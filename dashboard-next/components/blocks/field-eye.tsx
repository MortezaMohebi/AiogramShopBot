"use client";

import { useState } from "react";
import { Eye, EyeOff, LockKeyhole } from "lucide-react";

interface FieldEyeProps {
  name?: string;
  label: string;
  initial?: boolean;
  required?: boolean;
  onChange?: () => void;
}

/**
 * A customer-visibility control, not an administrator display toggle.
 *
 * Required commerce fields cannot be hidden. Optional fields are serialized
 * as explicit booleans, persisted per product, and enforced in both bots.
 */
export function FieldEye({
  name,
  label,
  initial = true,
  required = false,
  onChange,
}: FieldEyeProps) {
  const [visible, setVisible] = useState(initial);

  return (
    <span className="inline-flex items-center gap-2">
      {name ? (
        <input type="hidden" name={name} value={String(required || visible)} />
      ) : null}
      <button
        type="button"
        disabled={required}
        aria-pressed={required || visible}
        aria-label={required
          ? "نمایش " + label + " برای مشتری اجباری است"
          : (visible ? "پنهان‌کردن " : "نمایش ") + label + " برای مشتری"}
        title={required
          ? "اطلاعات ضروری خرید همیشه نمایش داده می‌شوند"
          : "کنترل نمایش این فیلد و مقدار آن در تلگرام و بله"}
        onClick={() => {
          setVisible((previous) => !previous);
          onChange?.();
        }}
        className={
          "inline-flex size-9 shrink-0 items-center justify-center rounded-md " +
          "border border-input focus-visible:outline-2 focus-visible:outline-ring " +
          (required
            ? "cursor-not-allowed text-muted-foreground/70"
            : visible
              ? "text-primary hover:bg-accent"
              : "bg-muted text-muted-foreground hover:bg-accent")
        }
      >
        {required
          ? <LockKeyhole aria-hidden="true" className="size-4" />
          : visible
            ? <Eye aria-hidden="true" className="size-4" />
            : <EyeOff aria-hidden="true" className="size-4" />}
      </button>
      <span className="text-xs text-muted-foreground">
        {required ? "اجباری" : visible ? "نمایش به مشتری" : "مخفی از مشتری"}
      </span>
    </span>
  );
}
