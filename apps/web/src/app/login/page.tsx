import type { Metadata } from "next";

import { AuthPanel } from "@/components/auth/auth-panel";

export const metadata: Metadata = { title: "Sign in" };

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function LoginPage({ searchParams }: PageProps) {
  const next = (await searchParams).next;
  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-12">
      <AuthPanel mode="login" nextParam={typeof next === "string" ? next : undefined} />
    </main>
  );
}
