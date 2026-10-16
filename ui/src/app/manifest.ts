import type { MetadataRoute } from "next";

// Icons carry the cross from the client logo (public/brand, see README there).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ClaimPilot",
    short_name: "ClaimPilot",
    description: "Review queue for travel-insurance claims",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#ffffff",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
