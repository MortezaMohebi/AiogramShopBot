/** The dashboard can change these named features, never start a host command. */
export const services = {
  receivers: { title: "دریافت پیام ربات‌ها", note: "راه‌اندازی دریافت پیام هر ربات پس از تأیید توکن و انتخاب روش اتصال انجام می‌شود.", href: "/bots" },
  "relay-pool": { title: "اتصال‌های Relay تلگرام", note: "تنها Relay و مسیر تأییدشده برای همان ربات استفاده می‌شود.", href: "/relay-workers" },
  "workflow-runtime": { title: "اجرای گردش‌کار", note: "اجرای هر گردش‌کار به انتشار و فعال‌سازی جداگانه برای فروشگاه و ربات نیاز دارد.", href: "/studio/workflows" },
  "telegram-fiat": { title: "درگاه ریالی تلگرام", note: "برای کالای فیزیکی و تنها با درگاه تأییدشده‌ای که ریال را پشتیبانی کند.", href: "/payment-accounts" },
  "telegram-stars": { title: "پرداخت Telegram Stars", note: "هر ربات فقط از حساب پرداختی که به آن اختصاص یافته استفاده می‌کند.", href: "/payment-accounts" },
  "telegram-stars-refunds": { title: "بازپرداخت Telegram Stars", note: "هر بازپرداخت از پروندهٔ همان پرداخت بررسی و تأیید می‌شود.", href: "/finance" },
  "bale-wallet": { title: "کیف پول بله", note: "برای هر ربات به حساب پرداخت فعال و اختصاص‌یافته نیاز است.", href: "/payment-accounts" },
  broadcast: { title: "ارسال کمپین‌ها", note: "شروع هر کمپین به تأیید مدیر و رضایت گیرندگان نیاز دارد. فعال‌کردن این سرویس کمپین جدیدی شروع نمی‌کند.", href: "/campaigns" },
  "bale-paid-broadcast": { title: "ارسال پولی بله", note: "ارسال Business فقط در محدودهٔ بودجهٔ تأییدشدهٔ همان کمپین انجام می‌شود.", href: "/campaigns" },
  "digital-delivery": { title: "تحویل دیجیتال", note: "تحویل فایل خصوصی فقط برای خریدهای دارای پرداخت تأییدشده انجام می‌شود.", href: "/digital-deliveries" },
  mcp: { title: "اتصال MCP گردش‌کارها", note: "تنها Gateway و کلیدهای مورد اعتماد این نصب می‌توانند از اتصال استفاده کنند.", href: "/account/mcp" },
  "customer-notifications": { title: "اعلان‌های مشتریان", note: "اعلان‌های در صف برای ربات فعال و مطابق ترجیحات مشتری ارسال می‌شوند.", href: "/customer-notifications" },
} as const;

export type ServiceKey = keyof typeof services;
export function isServiceKey(key: string): key is ServiceKey {
  return Object.hasOwn(services, key);
}

export interface ServiceControl {
  key: ServiceKey;
  override: boolean | null;
  default: boolean;
  enabled: boolean;
  blocked_reason: string | null;
  version: number;
}

export const serviceGroups: { title: string; keys: ServiceKey[] }[] = [
  { title: "ربات‌ها و گردش‌کار", keys: ["receivers", "relay-pool", "workflow-runtime", "mcp"] },
  { title: "پرداخت و بازپرداخت", keys: ["telegram-fiat", "telegram-stars", "telegram-stars-refunds", "bale-wallet"] },
  { title: "ارسال و تحویل", keys: ["broadcast", "bale-paid-broadcast", "digital-delivery", "customer-notifications"] },
];

export const prerequisiteMessages: Record<string, string> = {
  mcp_trust_unconfigured: "اعتماد به Gateway و کلیدهای عمومی MCP برای این نصب تنظیم نشده است.",
  emergency_stop: "توقف اضطراری گردش‌کار فعال است.",
  irr_provider_unconfigured: "ابتدا پشتیبانی ریال و واحد مبلغ را با ارائه‌دهندهٔ درگاه تأیید و تنظیم کنید.",
  paid_budget_unconfigured: "حالت Business بله و سقف هزینه برای این نصب تنظیم نشده است.",
  private_storage_unconfigured: "فضای خصوصی تحویل فایل آماده نیست.",
  relay_origins_unconfigured: "نشانی Relay مجاز برای این نصب تنظیم نشده است.",
};
