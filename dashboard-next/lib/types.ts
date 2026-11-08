/** Shared read contracts for the typed Next.js admin UI. */

export type StaffRole =
  | "superadmin" | "sales" | "content" | "finance" | "marketing" | "viewer";

export interface Staff {
  id: number;
  username: string;
  role: StaffRole;
}

export interface ChannelStats {
  platform: "telegram" | "bale";
  customers: number;
  opted_in: number;
  orders: number;
  paid_orders: number;
  review_orders: number;
  paid_unfulfilled: number;
  refunded: number;
  gross_paid_irr: string;
  store_credit_irr: string;
  telegram_stars_xtr: number;
}

export interface Order {
  id: number;
  platform: string;
  user_id?: string;
  name: string;
  status: string;
  provider?: string;
  total_irr: string;
  total_stars_snapshot?: number | null;
  payment_currency?: string | null;
  payment_amount?: string | null;
  created_at: string;
}

export interface Overview {
  products: number;
  published_products: number;
  open_refunds: number;
  channels: ChannelStats[];
  recent_orders: Order[];
  campaigns: CampaignSummary;
}

export interface Product {
  id: number;
  sku: string;
  external_ref: string | null;
  external_id?: string;
  store_id: string;
  uom_id: string;
  purchase_uom_id: string | null;
  category_id: number | null;
  name: string;
  description: string;
  price_irr: string;
  price_stars: number | null;
  digital_delivery_mode: "none" | "file" | "license";
  show_description?: boolean;
  show_stock?: boolean;
  show_media?: boolean;
  show_reviews?: boolean;
  stock_quantity: number;
  requires_shipping: boolean;
  product_type: "physical" | "digital";
  position: number;
  is_published: boolean;
}

export interface Category {
  id: number;
  name: string;
  position: number;
  is_published: boolean;
}

export interface Customer {
  id: number;
  platform: "telegram" | "bale";
  user_id: string;
  name: string | null;
  username: string | null;
  is_blocked: boolean;
  allow_announcements: boolean;
}

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface CampaignSummary {
  queued: number;
  sent: number;
  skipped: number;
  unknown: number;
}

export interface Campaign {
  id: number;
  title: string;
  text: string;
  audience: "all" | "telegram" | "bale";
  status: string;
  bale_mode: string;
  max_paid_calls: number;
  paid_calls_reserved: number;
  counts: Record<string, number>;
}

export interface Report {
  channels: ChannelStats[];
  campaigns: CampaignSummary;
  open_refund_cases: number;
  credit_issued_irr: string;
  credit_spent_irr: string;
  top_products: Array<{product_id: number; name: string; quantity: number}>;
  since: string | null;
}

export interface ShopSettings {
  brand_name: string;
  welcome_message: string;
  faq_text: string;
  support_url: string;
}
