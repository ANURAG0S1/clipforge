"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, Plus, Scissors } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { meQueryKey } from "@/components/app/auth-guard";
import { Button } from "@/components/ui/button";
import { fetchMe, logout } from "@/lib/auth";

export function AppHeader() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: meQueryKey, queryFn: ({ signal }) => fetchMe(signal) });
  const [signingOut, setSigningOut] = useState(false);

  async function handleLogout(): Promise<void> {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      queryClient.clear();
      router.replace("/login");
    }
  }

  return (
    <header className="bg-background/90 sticky top-0 z-10 border-b backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="bg-primary text-primary-foreground inline-flex size-7 items-center justify-center rounded-md">
            <Scissors aria-hidden="true" className="size-4" />
          </span>
          ClipForge
        </Link>
        <div className="ml-auto flex items-center gap-2">
          {me.data !== undefined && (
            <span className="text-muted-foreground hidden text-sm sm:inline">{me.data.email}</span>
          )}
          <Button asChild size="sm">
            <Link href="/new">
              <Plus aria-hidden="true" />
              New project
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void handleLogout()}
            disabled={signingOut}
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut aria-hidden="true" />
          </Button>
        </div>
      </div>
    </header>
  );
}
