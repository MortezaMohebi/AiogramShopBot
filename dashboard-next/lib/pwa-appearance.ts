/** Public installation identity from the internal application service. */
export interface PwaAppearance {
  name: string;
  short_name: string;
  theme_color: string;
  version: number;
}

export const defaultAppearance: PwaAppearance = {
  name: "مدیریت فروشگاه", short_name: "فروشگاه", theme_color: "#146b66", version: 0,
};

export async function publicAppearance(): Promise<PwaAppearance> {
  const host = process.env.SHOP_FASTAPI_INTERNAL_URL;
  if (!host) return defaultAppearance;
  try {
    const origin = new URL(host);
    if (!["http:", "https:"].includes(origin.protocol)) return defaultAppearance;
    const response = await fetch(new URL("/pwa/appearance", origin), {
      cache: "no-store", signal: AbortSignal.timeout(3_000),
    });
    if (!response.ok) return defaultAppearance;
    const value: unknown = await response.json();
    if (!value || typeof value !== "object") return defaultAppearance;
    const data = value as Partial<PwaAppearance>;
    return typeof data.name === "string" && data.name.length <= 80
      && typeof data.short_name === "string" && data.short_name.length <= 24
      && typeof data.theme_color === "string" && /^#[0-9a-f]{6}$/i.test(data.theme_color)
      && Number.isSafeInteger(data.version) && Number(data.version) >= 0
      ? data as PwaAppearance : defaultAppearance;
  } catch {
    return defaultAppearance;
  }
}
