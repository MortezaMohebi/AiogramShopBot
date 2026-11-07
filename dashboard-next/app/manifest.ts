import type { MetadataRoute } from "next";

/** Install the current private dashboard origin without URL parameters or credentials. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "مدیریت فروشگاه",
    short_name: "فروشگاه",
    description: "پنل مدیریت فروشگاه تلگرام و بله",
    lang: "fa",
    dir: "rtl",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f7f8fa",
    theme_color: "#146b66",
    icons: [
      { src: "/pwa/icon/192", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/pwa/icon/512", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/pwa/icon/maskable", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
