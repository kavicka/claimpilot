import type { Metadata } from "next";
import { Courier_Prime, Inter, Plus_Jakarta_Sans } from "next/font/google";

import { Providers } from "@/components/shell/providers";

import "./globals.css";

// The design system's three families (packages/claimpilot-ui README). globals.css points the
// --font-inter / --font-jakarta / --font-mono tokens at these.
const inter = Inter({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600", "800"],
  variable: "--font-inter-next",
});
const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin", "latin-ext"],
  weight: ["500", "600", "700"],
  variable: "--font-jakarta-next",
});
const mono = Courier_Prime({
  subsets: ["latin", "latin-ext"],
  weight: ["400"],
  variable: "--font-mono-next",
});

export const metadata: Metadata = {
  title: { default: "ClaimPilot", template: "%s · ClaimPilot" },
  description: "Review queue for travel-insurance claims",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jakarta.variable} ${mono.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
