import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";

const API = process.env.CLAIMPILOT_API_URL ?? "http://127.0.0.1:4400";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  agentRules: false,
  devIndicators: false,
  // The design system ships TypeScript source (packages/claimpilot-ui).
  transpilePackages: ["@claimpilot/ui"],
  // The container image (ui/Dockerfile) runs the standalone server; local dev and e2e do not.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // ui/ is a standalone app; stop Turbopack from picking up lockfiles further up the tree.
  turbopack: { root: path.dirname(fileURLToPath(import.meta.url)) },
  // The browser only ever talks to this origin; the session cookie stays same-origin.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default config;
