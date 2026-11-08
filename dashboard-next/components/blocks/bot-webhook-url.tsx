"use client";

import { useState } from "react";
import { revealBotWebhookUrl } from "@/app/(console)/bots/[id]/actions";
import { ReauthenticationForm } from "@/components/blocks/reauthentication";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const errors: Record<string, string> = {
  invalid_operation_state: "برای این ربات وب‌هوک فعالی وجود ندارد.",
  webhook_url_invalid: "آدرس عمومی HTTPS وب‌هوک در سرور پیکربندی نشده است.",
  permission_denied: "حساب فعلی اجازهٔ مشاهدهٔ آدرس وب‌هوک را ندارد.",
};

export function BotWebhookUrl({ botId }: { botId: string }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsProof, setNeedsProof] = useState(false);
  const [error, setError] = useState("");
  const [copyStatus, setCopyStatus] = useState("");

  async function reveal(verified = false) {
    setBusy(true);
    setNeedsProof(false);
    setError("");
    try {
      const result = await revealBotWebhookUrl(botId);
      if ("url" in result) {
        setUrl(result.url);
      } else if (result.error === "reauthentication_required" && !verified) {
        setNeedsProof(true);
      } else {
        setError(errors[result.error] ?? "آدرس وب‌هوک دریافت نشد. دوباره تلاش کنید.");
      }
    } catch {
      setError("آدرس وب‌هوک دریافت نشد. دوباره تلاش کنید.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopyStatus("آدرس کپی شد.");
    } catch {
      setCopyStatus("کپی خودکار انجام نشد. آدرس را از کادر انتخاب و کپی کنید.");
    }
  }

  return <div className="space-y-3 rounded-lg border p-4">
    {url ? <>
      <label className="block space-y-2 font-medium">آدرس پیکربندی‌شدهٔ وب‌هوک
        <Input dir="ltr" className="text-left font-mono text-xs" value={url} readOnly
          autoComplete="off" spellCheck={false} onFocus={event => event.currentTarget.select()} />
      </label>
      <p className="text-xs text-muted-foreground">این آدرس حاوی کلید دریافت پیام ربات است.</p>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={copy}>کپی آدرس</Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => {
          setUrl("");
          setCopyStatus("");
        }}>پنهان کردن</Button>
        {copyStatus ? <span role="status" className="text-xs text-muted-foreground">{copyStatus}</span> : null}
      </div>
    </> : needsProof ?
      <ReauthenticationForm onCancel={() => setNeedsProof(false)} onVerified={() => reveal(true)} /> :
      <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => reveal()}>
        {busy ? "در حال دریافت آدرس…" : "نمایش آدرس وب‌هوک"}
      </Button>}
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
  </div>;
}
