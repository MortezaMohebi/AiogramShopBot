/** Immutable money fields shared by order, review and refund summaries. */
export interface OrderAmount {
  platform: string;
  total_irr: string;
  total_stars_snapshot?: number | null;
  payment_currency?: string | null;
  payment_amount?: string | null;
}

/** Display the actual payment unit without converting Stars to nominal rials. */
export function formatOrderAmount(order: OrderAmount): string {
  const stars = order.platform === "telegram" &&
    (order.payment_currency === "XTR" || order.total_stars_snapshot != null);
  const amount = stars
    ? order.payment_currency === "XTR"
      ? order.payment_amount ?? order.total_stars_snapshot
      : order.total_stars_snapshot
    : order.total_irr;
  try {
    if (amount == null) return "—";
    const value = BigInt(amount);
    if (value < BigInt(0)) return "—";
    return `${new Intl.NumberFormat("fa-IR").format(value)} ${stars ? "Stars (XTR)" : "ریال"}`;
  } catch {
    return "—";
  }
}
