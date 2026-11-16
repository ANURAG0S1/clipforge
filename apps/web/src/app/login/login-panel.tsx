"use client";

import { Scissors } from "lucide-react";
import { useRouter } from "next/navigation";

import { LoginForm } from "@/components/auth/login-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { login } from "@/lib/auth";

export function LoginPanel() {
  const router = useRouter();
  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="items-center text-center">
        <span className="bg-primary text-primary-foreground mb-2 inline-flex size-10 items-center justify-center rounded-lg">
          <Scissors aria-hidden="true" className="size-5" />
        </span>
        <CardTitle>Sign in to ClipForge</CardTitle>
        <CardDescription>Turn long videos into short, captioned clips.</CardDescription>
      </CardHeader>
      <CardContent>
        <LoginForm onSubmit={login} onSuccess={() => router.push("/")} />
      </CardContent>
    </Card>
  );
}
