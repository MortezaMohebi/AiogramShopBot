import type { NextConfig } from "next";

// Standalone output permits a small isolated Docker service.
const nextConfig: NextConfig = {
  output: "standalone",
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
