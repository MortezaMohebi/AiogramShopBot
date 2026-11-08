"use client";

import { useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";

export function VerifyBotSubmitButton({ verified }: { verified: boolean }) {
  const { pending } = useFormStatus();
  const label = verified ? "بررسی دوباره با getMe" : "تأیید با getMe";
  return <Button size="sm" type="submit" variant="outline" disabled={pending}>
    {pending ? "در حال بررسی هویت…" : label}
  </Button>;
}
