import type { NextConfig } from "next";

/**
 * An optional CDN serves ONLY immutable /_next/static assets for this build.
 * Never move API/auth requests or private media to a public asset CDN.
 */
function assetCdnOrigin(): string | undefined {
  const value = process.env.NEXT_ADMIN_CDN_URL?.trim();
  if (!value) return undefined;

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("NEXT_ADMIN_CDN_URL must be an HTTPS origin.");
  }
  if (
    url.protocol !== "https:" ||
    value !== url.origin ||
    url.username || url.password ||
    url.pathname !== "/" || url.search || url.hash
  ) {
    throw new Error("NEXT_ADMIN_CDN_URL must be an HTTPS origin.");
  }
  return url.origin;
}

// Standalone output permits a small isolated Docker service.
const nextConfig: NextConfig = {
  output: "standalone",
  assetPrefix: assetCdnOrigin(),
  reactStrictMode: true,
  poweredByHeader: false,
  // Permit exactly this Codespaces hostname for reverse-proxied Server Actions.
  experimental: {
    serverActions: {
      allowedOrigins: process.env.NEXT_ADMIN_PUBLIC_ORIGIN
        ? [new URL(process.env.NEXT_ADMIN_PUBLIC_ORIGIN).host]
        : [],
    },
  },
};

export default nextConfig;
