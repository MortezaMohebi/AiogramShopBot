import type { NextConfig } from "next";

// Standalone output permits a small isolated Docker service.
const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
