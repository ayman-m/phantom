import type { Metadata } from "next";
import { AuthGate } from "@/components/auth/auth-gate";
import "./globals.css";

export const metadata: Metadata = {
  title: "Phantom Agent",
  description: "Continuous SOC simulation agent — control plane",
  // Favicon resolves via Next.js's app-icon file convention:
  // app/icon.svg is auto-discovered and emits a hashed
  // <link rel="icon" type="image/svg+xml" href="/icon.svg?<hash>"/>
  // tag at build time. Don't set `icons:` here — doing so would
  // override the auto-discovered tag and skip cache-busting.
};

/**
 * Root layout — Spark Ocean Navy theme.
 *
 * Loads the Spark font stack (Space Grotesk for headlines, Manrope for
 * body, JetBrains Mono for code, Material Symbols Outlined for icons)
 * from Google Fonts, then mounts:
 *   AuthGate → LoginScreen | AppShell (sidebar + main).
 *
 * Chat sessions are not held in a client-side provider or browser
 * storage; they flow through /api/v1/sessions (server-side).
 */
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Manrope:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen text-on-surface font-body selection:bg-primary/30 selection:text-primary">
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
