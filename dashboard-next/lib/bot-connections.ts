/** Safe, token-free runtime configuration delivered by the signed BFF. */
export interface BotConnections {
  database: "connected";
  telegram: {
    configured: boolean;
    update_mode: "webhook" | "polling";
    pending_update_mode: "webhook" | "polling" | null;
    api_transport: "direct" | "http_proxy" | "cloudflare_worker";
    webhook_url: string | null;
    worker_configured: boolean;
    proxy_configured: boolean;
    supported_update_modes: string[];
  };
  bale: {
    configured: boolean;
    update_mode: "webhook";
    webhook_url_label: string | null;
    supported_update_modes: string[];
  };
  runtime_note: string;
}

export interface BotProviderProbe {
  telegram: {
    status: "connected" | "unavailable" | "not_configured";
    username?: string | null;
    pending_updates?: number;
    webhook_matches?: boolean;
    provider_mode?: "webhook" | "getUpdates";
  };
  bale: {
    status: "connected" | "unavailable" | "not_configured";
    username?: string | null;
    webhook_status?: "matching" | "different" | "unsupported_or_unavailable";
  };
}
