"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Scissors } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { AuthForm, type AuthMode } from "@/components/auth/auth-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { login, register } from "@/lib/auth";
import { safeNextPath } from "@/lib/redirect";

const COPY: Record<
  AuthMode,
  { title: string; switchText: string; switchLink: string; href: string }
> = {
  login: {
    title: "Sign in to ClipForge",
    switchText: "New here?",
    switchLink: "Create an account",
    href: "/register",
  },
  register: {
    title: "Create your ClipForge account",
    switchText: "Already have an account?",
    switchLink: "Sign in",
    href: "/login",
  },
};

export function AuthPanel({ mode }: { mode: AuthMode }) {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const next = safeNextPath(params.get("next"));
  const copy = COPY[mode];
  const switchHref = next === "/" ? copy.href : `${copy.href}?next=${encodeURIComponent(next)}`;

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="items-center text-center">
        <span className="bg-primary text-primary-foreground mb-2 inline-flex size-10 items-center justify-center rounded-lg">
          <Scissors aria-hidden="true" className="size-5" />
        </span>
        <CardTitle>{copy.title}</CardTitle>
        <CardDescription>Turn long videos into short, captioned clips.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <AuthForm
          mode={mode}
          onSubmit={mode === "login" ? login : register}
          onSuccess={() => {
            queryClient.clear();
            router.replace(next);
          }}
        />
        <p className="text-muted-foreground text-center text-sm">
          {copy.switchText}{" "}
          <Link
            href={switchHref}
            className="text-foreground font-medium underline underline-offset-4"
          >
            {copy.switchLink}
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
