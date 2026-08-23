import type { Metadata } from "next";
import { Atkinson_Hyperlegible, Crimson_Pro, EB_Garamond } from "next/font/google";

import { AppHeader } from "@/components/app-header";

import { AppProviders } from "./providers";
import "./globals.css";

const atkinson = Atkinson_Hyperlegible({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-atkinson",
  display: "swap",
});

const crimson = Crimson_Pro({
  subsets: ["latin"],
  variable: "--font-crimson",
  display: "swap",
});

const garamond = EB_Garamond({
  subsets: ["latin"],
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
    <html lang="en" className={`${atkinson.variable} ${crimson.variable} ${garamond.variable}`}>
      <body suppressHydrationWarning className="min-h-svh font-sans antialiased">
        <AppProviders>
          <AppHeader />
          {children}
        </AppProviders>
      </body>
    </html>
  );
}
