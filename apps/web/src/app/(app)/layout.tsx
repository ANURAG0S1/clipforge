import type { ReactNode } from "react";

import { AppHeader } from "@/components/app/app-header";
import { AuthGuard } from "@/components/app/auth-guard";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <AppHeader />
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:py-8">{children}</main>
    </AuthGuard>
  );
}
