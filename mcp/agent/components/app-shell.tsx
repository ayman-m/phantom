"use client";

import { Sidebar, useSidebarCollapsed } from "@/components/sidebar";
import { Providers } from "@/components/providers";
import { cn } from "@/lib/utils";

/**
 * Application chrome — sidebar + main content + decorative background
 * glows. Lifted from spark/services/ui's `app-shell.tsx`. Auth + setup
 * gating live one level up in `components/auth/auth-gate.tsx`; by the
 * time AppShell renders, the operator is authenticated and setup is
 * complete. Workspace-route handling (`/w/...`) is dropped — phantom
 * is single-tenant.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const collapsed = useSidebarCollapsed();

  return (
    <Providers>
      <Sidebar />
      <main
        className={cn(
          "min-h-screen transition-all duration-300",
          collapsed ? "ml-16" : "ml-64"
        )}
      >
        {children}
      </main>
      {/* Floating decorative background glows — Ocean Navy theme */}
      <div className="fixed top-0 right-0 -z-10 w-[600px] h-[600px] bg-[#1f7bff]/5 rounded-full blur-[120px] pointer-events-none" />
      <div
        className={cn(
          "fixed bottom-0 -z-10 w-[400px] h-[400px] bg-[#00f5ff]/5 rounded-full blur-[100px] pointer-events-none transition-all duration-300",
          collapsed ? "left-16" : "left-64"
        )}
      />
    </Providers>
  );
}
