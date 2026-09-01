import type { Metadata } from "next";
import { Be_Vietnam_Pro, Crimson_Pro, EB_Garamond } from "next/font/google";

import { AppHeader } from "@/components/app-header";

import { AppProviders } from "./providers";
import "./globals.css";

const beVietnam = Be_Vietnam_Pro({
  subsets: ["latin", "latin-ext", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-be-vietnam",
  display: "swap",
});

const crimson = Crimson_Pro({
  subsets: ["latin", "latin-ext", "vietnamese"],
  variable: "--font-crimson",
  display: "swap",
});

const garamond = EB_Garamond({
  subsets: ["latin", "latin-ext", "vietnamese"],
  variable: "--font-garamond",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SpecResearch Loop",
  description:
    "Turn a vague research idea into a verified Research Spec through a human-in-the-loop workflow. Evaluates readiness criteria; does not guarantee conference acceptance.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${beVietnam.variable} ${crimson.variable} ${garamond.variable}`}>
      <body suppressHydrationWarning className="min-h-svh font-sans antialiased">
        <AppProviders>
          <AppHeader />
          {children}
        </AppProviders>
      </body>
    </html>
  );
}
