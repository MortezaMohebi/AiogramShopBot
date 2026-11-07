/** Store-owned campaign contracts; no provider credentials reach the browser. */
export interface Campaign {
  id: number;
  store_id: string;
  store_name: string;
  bot_id: string | null;
  bot_name: string | null;
  bot_platform: "telegram" | "bale" | null;
  title: string;
  text: string;
  audience: "all" | "telegram" | "bale";
  status: string;
  bale_mode: string;
  max_paid_calls: number;
  paid_calls_reserved: number;
  bale_recipients: number;
  media_count: number;
  counts: Record<string, number>;
}

export interface CampaignBotOptions {
  store_id: string;
  store_name: string;
  bots: Array<{ id: string; name: string; platform: "telegram" | "bale" }>;
}
