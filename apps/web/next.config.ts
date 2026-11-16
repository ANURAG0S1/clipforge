import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  outputFileTracingRoot: new URL("../../", import.meta.url).pathname,
  transpilePackages: ["@clipforge/shared-types"],
};

export default nextConfig;
