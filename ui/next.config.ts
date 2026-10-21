import { realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";

const API = process.env.CLAIMPILOT_API_URL ?? "http://127.0.0.1:4400";
const ui = path.dirname(fileURLToPath(import.meta.url));

// The design system (@crm-ui/react) is linked from ~/programming/crm-ui, outside ui/. Turbopack only
// reads files under its root, so the root is the nearest directory holding both.
function turbopackRoot(): string {
  let designSystem: string;
  try {
    designSystem = realpathSync(path.join(ui, "node_modules/@crm-ui/react"));
  } catch {
    return ui; // not installed yet
  }
  let root = ui;
  while (path.relative(root, designSystem).startsWith("..")) root = path.dirname(root);
  return root;
}

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  agentRules: false,
  devIndicators: false,
  // The design system ships TypeScript source.
  transpilePackages: ["@crm-ui/react"],
  // The container image (ui/Dockerfile) runs the standalone server; local dev and e2e do not.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // Set explicitly so Turbopack does not pick up lockfiles further up the tree.
  turbopack: { root: turbopackRoot() },
  // The browser only ever talks to this origin; the session cookie stays same-origin.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default config;
