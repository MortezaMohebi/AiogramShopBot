/** Redacted contracts for the many-to-many outbound Worker registry. */

export interface RelayWorker {
  id: string;
  slug: string;
  name: string;
  origin: string;
  status: "draft" | "active" | "paused" | "disabled";
  max_rps: number;
  max_inflight: number;
  version: number;
  bot_count: number;
  updated_at: string | null;
}

export interface RelayWorkersSnapshot {
  items: RelayWorker[];
  enabled: boolean;
  approved_origins: string[];
}

export interface BotRelayRoute {
  bot_id: string;
  worker_id: string;
  worker_name: string;
  worker_status: RelayWorker["status"];
  priority: number;
  status: "staged" | "active" | "paused";
  version: number;
  credential_version: number | null;
  credential_state: "staged" | "active" | "retiring" | "revoked" | null;
  credential_verified_at: string | null;
}

export interface BotRelaySnapshot {
  bot_id: string;
  items: BotRelayRoute[];
}
