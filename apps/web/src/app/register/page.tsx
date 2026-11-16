import type { Metadata } from "next";

import { AuthPanel } from "@/components/auth/auth-panel";

export const metadata: Metadata = { title: "Create account" };

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RegisterPage({ searchParams }: PageProps) {
  const next = (await searchParams).next;
  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-12">
      <AuthPanel mode="register" nextParam={typeof next === "string" ? next : undefined} />
    </main>
  );
}
