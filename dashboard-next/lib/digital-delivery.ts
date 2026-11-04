/** Non-secret metadata for Store-owned digital merchandise and delivery logs. */

export type DigitalKind = "file" | "license";

export interface DigitalAssetSnapshot {
  product_id: number;
  configured: boolean;
  id?: number;
  kind?: DigitalKind;
  filename?: string | null;
  size_bytes?: number | null;
  version?: number;
  codes?: Record<"available" | "reserved" | "delivered", number>;
}

export interface DigitalDeliveryReceipt {
  id: number;
  store_id: string;
  order_id: number;
  bot_id: string;
  platform: "telegram" | "bale";
  asset_id: number;
  status: "queued" | "sending" | "delivered" | "needs_review" | "blocked";
  provider_message_id: number | null;
  failure_code: string | null;
  delivered_at: string | null;
}

export interface MixedBatchReceipt {
  id: string;
  store_id: string;
  bot_id: string;
  platform: "telegram";
  created_at: string;
  orders: Array<{
    id: number;
    part: "physical" | "digital";
    status: string;
    provider: string;
    currency: "IRR" | "XTR";
    amount_irr: string;
    amount_stars: number | null;
    paid_at: string | null;
  }>;
}
