import type { MetadataRoute } from "next";
import { publicAppearance } from "../lib/pwa-appearance";

export const dynamic = "force-dynamic";

/** Install the current private dashboard origin without URL parameters or credentials. */
export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const settings = await publicAppearance();
  return {
    id: "/",
    name: settings.name,
    short_name: settings.short_name,
    description: "پنل مدیریت فروشگاه تلگرام و بله",
    lang: "fa",
    dir: "rtl",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f7f8fa",
    theme_color: settings.theme_color,
    icons: [
      { src: `/pwa/icon/192?v=${settings.version}`, sizes: "192x192", type: "image/png", purpose: "any" },
      { src: `/pwa/icon/512?v=${settings.version}`, sizes: "512x512", type: "image/png", purpose: "any" },
      { src: `/pwa/icon/maskable?v=${settings.version}`, sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
