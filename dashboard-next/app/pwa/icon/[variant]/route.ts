import { createElement } from "react";
import { ImageResponse } from "next/og";
import { publicAppearance } from "../../../../lib/pwa-appearance";

const iconSizes = new Map([
  ["192", 192],
  ["512", 512],
  ["maskable", 512],
  ["apple", 180],
]);

export const dynamic = "force-dynamic";

/** Generate first-party PNG artwork without a remote font or asset dependency. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ variant: string }> },
) {
  const { variant } = await params;
  const size = iconSizes.get(variant);
  if (size === undefined) return new Response(null, { status: 404 });
  const settings = await publicAppearance();
  const glyph = Math.round(size * (variant === "maskable" ? 0.51 : 0.62));

  return new ImageResponse(createElement("div", {
    style: {
      width: "100%", height: "100%", display: "flex",
      alignItems: "center", justifyContent: "center",
      background: `linear-gradient(145deg, ${settings.theme_color} 0%, #101e31 100%)`,
    },
  }, createElement("svg", {
    width: glyph, height: glyph, viewBox: "0 0 100 100", fill: "none",
    stroke: "#fff", strokeWidth: 6, strokeLinecap: "round", strokeLinejoin: "round",
  },
  createElement("path", { d: "M22 38h56l-4 43a8 8 0 0 1-8 7H34a8 8 0 0 1-8-7z" }),
  createElement("path", { d: "M37 39v-8a13 13 0 0 1 26 0v8" }),
  createElement("path", { d: "M40 59h21m-21 12h15" }),
  createElement("circle", { cx: 72, cy: 67, r: 10, fill: "#bce9d8", stroke: "none" }),
  )), { width: size, height: size, headers: {
    "Cache-Control": "no-store, max-age=0", "X-Content-Type-Options": "nosniff",
  } });
}
