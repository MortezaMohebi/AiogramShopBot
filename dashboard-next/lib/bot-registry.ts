/** Redacted, per-bot API contracts; credentials are never serialized. */

export type BotPlatform = "telegram" | "bale";
export type BotDesiredState = "active" | "paused" | "maintenance" | "disabled";
export type BotRegistryStatus =
  | "draft" | "active" | "paused" | "maintenance" | "disabled";

export interface StoreRecord {
  id: string;
  slug: string;
  name: string;
  state: string;
}

export interface BotCredentialStatus {
  version: number;
  source: "encrypted";
  state: "staged" | "active" | "revoked";
  created_at: string | null;
  has_secret: boolean;
  verified_at: string | null;
  verified_bot_id: string | null;
}

export interface BotOperations {
  desired_state: BotDesiredState;
  state_label: string;
  runtime_ready: boolean;
  welcome_message: string | null;
  maintenance_message: string | null;
  support_url: string | null;
  owner_staff_id: number | null;
  environment: "staging" | "production";
  reason: string | null;
  updated_at: string | null;
}

export interface BotRecord {
  id: string;
  store_id: string;
  slug: string;
  name: string;
  platform: BotPlatform;
  provider_bot_id: string | null;
  provider_username: string | null;
  status: BotRegistryStatus;
  runtime_owner: "registry";
  version: number;
  credential_version: number | null;
  credentials: BotCredentialStatus[];
  verified_at: string | null;
  operations: BotOperations;
}

export interface BotRegistrySnapshot {
  stores: StoreRecord[];
  bots: BotRecord[];
  default_store_id: string;
  total_bots: number;
  page: number;
  page_size: number;
}

export interface BotHealthSnapshot {
  bot_id: string;
  runtime_owner: "registry";
  runtime_ready: boolean;
  desired_state: BotDesiredState;
  provider_api: "not_probed";
  verified_identity_at: string | null;
  receiver_status: string;
  receiver_mode: "webhook" | "polling" | null;
  received_last_at: string | null;
  processing_last_hour: number;
  needs_review_last_hour: number;
  has_live_credential: boolean;
}

/** No credential, opaque route binding or webhook secret is exposed. */
export interface BotReceiverSnapshot {
  configured: boolean;
  state: "staged" | "applying" | "active" | "paused" | "disabled" | "needs_review";
  mode: "webhook" | "polling" | null;
  version: number | null;
  credential_version: number | null;
  next_update_id: number | null;
  last_received_at: string | null;
  last_error_code: string | null;
  runtime_enabled: boolean;
  worker_ready: boolean;
}

export interface BotRegistryDetail {
  bot: BotRecord;
  health: BotHealthSnapshot;
  state_events: {
    id: string;
    actor_id: number;
    previous_state: BotDesiredState;
    next_state: BotDesiredState;
    reason: string | null;
    created_at: string | null;
  }[];
  events: {
    id: string;
    actor_id: number | null;
    action: string;
    credential_version: number | null;
    created_at: string | null;
  }[];
}

export function botPlatformLabel(platform: BotPlatform): string {
  return platform === "telegram" ? "تلگرام" : "بله";
}

export function botCredentialLabel(credential: BotCredentialStatus): string {
  if (credential.state === "staged") {
    return credential.verified_at ? "تأییدشده · در انتظار فعال‌سازی" : "در انتظار تأیید";
  }
  return ({ active: "فعال", revoked: "لغوشده", retiring: "در حال جایگزینی" } as Record<string, string>)[credential.state] ?? credential.state;
}

export function botRuntimeLabel(bot: BotRecord): string {
  if (bot.status === "draft") return "پیش‌نویس — دریافت پیام فعال نیست";
  return ({
    active: "فعال — اتصال مستقل",
    paused: "متوقف — تسویه محفوظ",
    maintenance: "نگهداری — تسویه محفوظ",
    disabled: "غیرفعال — تسویه محفوظ",
  } as const)[bot.operations.desired_state];
}
