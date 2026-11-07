import { createElement } from "react";
import { ImageResponse } from "next/og";

const iconSizes = new Map([
  ["192", 192],
  ["512", 512],
  ["maskable", 512],
  ["apple", 180],
]);

export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return Array.from(iconSizes.keys(), (variant) => ({ variant }));
}

/** Generate first-party PNG artwork without a remote font or asset dependency. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ variant: string }> },
) {
  const { variant } = await params;
  const size = iconSizes.get(variant);
  if (size === undefined) return new Response(null, { status: 404 });
  const glyph = Math.round(size * 0.65);

  return new ImageResponse(createElement("div", {
    style: {
      width: "100%", height: "100%", display: "flex",
      alignItems: "center", justifyContent: "center", backgroundColor: "#146b66",
    },
  }, createElement("svg", {
    width: glyph, height: glyph, viewBox: "0 0 24 24", fill: "none",
    stroke: "#fff", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round",
  },
  createElement("path", { d: "M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-5 4v-4a2.5 2.5 0 0 1-2-2.5z" }),
  createElement("path", { d: "M8 9h8m-8 3.5h5" }),
  )), { width: size, height: size });
}
