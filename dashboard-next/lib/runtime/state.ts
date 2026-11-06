/** Pure presentation policy. Every write is independently authorized and revalidated by the API. */
import type { Definition, BotChoice } from "../workflows/types";
import type { RuntimeOverview, RecoveryTarget, OutboxItem, ActionJob, PublicationPreview, RecoveryOperation } from "./types";
export const runLabels: Record<string, string> = {
  active: "در حال اجرا",
  waiting_input: "منتظر ورودی",
  waiting_action: "در صف Action",
  waiting_approval: "منتظر تأیید مسئول",
  waiting_timeout: "منتظر زمان",
  completed: "کامل‌شده",
  cancelled: "لغوشده",
  failed: "ناموفق",
  expired: "منقضی",
  suspended: "متوقف‌شده"
};
export const deliveryLabels: Record<string, string> = {
  pending: "در صف ارسال",
  sending: "در حال ارسال؛ نتیجه هنوز ثبت نشده",
  sent: "ارسال‌شده",
  failed: "ارسال ناموفق",
  retrying: "در انتظار تلاش مجدد",
  retryable: "در صف تلاش مجدد",
  dead_letter: "توقف ارسال؛ نیاز به بررسی",
  uncertain: "نتیجهٔ ارسال نامعلوم",
  cancelled: "ارسال لغوشده"
};
export const recoveryLabels: Record<RecoveryOperation, string> = {
  resume: "ادامهٔ اجرای متوقف‌شده",
  retry_failed: "بازیابی مرحلهٔ ناموفق",
  cancel: "لغو اجرا",
  mark_failed: "ثبت اجرا به‌عنوان ناموفق"
};
export function deliveryState(status: string) {
  return deliveryLabels[status] ?? status;
}
export function gateStatus(overview: RuntimeOverview, botId?: string): string {
  if (overview.global_killed) return "global_killed";
  if (!overview.global_enabled) return "global_disabled";
  const store = overview.gates.find(g => g.bot_id === null);
  if (store?.killed) return "store_killed";
  if (!store?.enabled) return "store_disabled";
  if (!botId) return "store_enabled";
  const bot = overview.gates.find(g => g.bot_id === botId);
  if (bot?.killed) return "bot_killed";
  return bot?.enabled ? "enabled" : "bot_disabled";
}
export const gateLabels: Record<string, string> = {
  global_killed: "توقف اضطراری سراسری فعال است",
  global_disabled: "Runtime از تنظیمات سرور خاموش است",
  store_killed: "توقف اضطراری فروشگاه فعال است",
  store_disabled: "اجرای فروشگاه غیرفعال است",
  store_enabled: "فروشگاه مجاز است؛ مجوز ربات و ورودی هم لازم است",
  bot_killed: "توقف اضطراری ربات فعال است",
  bot_disabled: "اجرای ربات غیرفعال است",
  enabled: "مجوز اجرا برقرار است؛ ورودی منتشرشده هم لازم است"
};
export function recoveryOperations(run: RecoveryTarget, canManage: boolean, now = Date.now()): RecoveryOperation[] {
  if (!canManage || ["completed", "cancelled", "expired"].includes(run.status)) return [];
  const result: RecoveryOperation[] = [];
  const unresolved = run.actions.some(a => ["uncertain", "running", "pending_external"].includes(a.status)) || run.outbox.some(o => ["sending", "uncertain"].includes(o.status) || /uncertain|unknown/.test(o.error_code ?? ""));
  if (!unresolved && Date.parse(run.expires_at) > now) {
    if (run.status === "suspended") result.push("resume");
    if (run.status === "failed") result.push("retry_failed");
  }
  if (run.status !== "failed") result.push("cancel", "mark_failed");
  return result;
}
export function canRetryDelivery(row: OutboxItem, canManage: boolean): boolean {
  return canManage && row.can_retry === true && row.expected_attempts === row.attempts && ["failed", "dead_letter", "retryable"].includes(row.status) && !/uncertain|unknown/.test(row.error_code ?? "");
}
export function canApproveAction(row: Pick<ActionJob, "status" | "can_approve" | "expected_version">, canManage: boolean): boolean {
  return canManage && row.can_approve === true && row.status === "waiting_approval" && Number.isSafeInteger(row.expected_version);
}
export function publicationCanActivate(preview: PublicationPreview, approved: boolean, canPublish: boolean, now = Date.now()): boolean {
  return canPublish && approved && preview.ready && Date.parse(preview.expires_at) > now;
}
export function validBindingChoices(definition: Definition, bots: BotChoice[]) {
  return bots.filter(bot => bot.status === "active" && definition.target_platforms.includes(bot.platform) && (definition.assignment.mode === "all_eligible" || definition.assignment.bot_ids.includes(bot.id))).flatMap(bot => definition.entry_points.map(entry => ({
    bot,
    entry
  })));
}
