"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { isUnauthorized } from "@/lib/api";
import { fetchMe } from "@/lib/auth";

export const meQueryKey = ["me"] as const;

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useQuery({ queryKey: meQueryKey, queryFn: ({ signal }) => fetchMe(signal) });
  const unauthenticated = me.isError && isUnauthorized(me.error);

  useEffect(() => {
    if (unauthenticated) {
      const next = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname)}`;
      router.replace(`/login${next}`);
    }
  }, [unauthenticated, pathname, router]);

  if (me.isPending || unauthenticated) {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status" aria-live="polite">
        <Loader2 className="text-muted-foreground size-6 animate-spin" aria-hidden="true" />
        <span className="sr-only">Loading…</span>
      </div>
    );
  }
  if (me.isError) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 px-4 text-center">
        <p role="alert" className="text-muted-foreground text-sm">
          We couldn&apos;t reach the server. Check that the API is running.
        </p>
        <Button variant="outline" onClick={() => void me.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  return <>{children}</>;
}
