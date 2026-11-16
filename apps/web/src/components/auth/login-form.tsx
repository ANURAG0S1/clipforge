"use client";

import { Loader2 } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { credentialsSchema, type Credentials } from "@/lib/auth";

type FieldErrors = Partial<Record<keyof Credentials, string>>;

export interface LoginFormProps {
  onSubmit: (credentials: Credentials) => Promise<void>;
  onSuccess?: () => void;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Incorrect email or password.";
    if (error.status === 429) return "Too many attempts. Wait a minute and try again.";
    if (error.status === 0) return error.detail;
  }
  return "Something went wrong. Please try again.";
}

export function LoginForm({ onSubmit, onSuccess }: LoginFormProps) {
  const id = useId();
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (pending) return;
    const data = new FormData(event.currentTarget);
    const parsed = credentialsSchema.safeParse({
      email: data.get("email") ?? "",
      password: data.get("password") ?? "",
    });
    if (!parsed.success) {
      const errors: FieldErrors = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0];
        if ((key === "email" || key === "password") && errors[key] === undefined) {
          errors[key] = issue.message;
        }
      }
      setFieldErrors(errors);
      setFormError(null);
      return;
    }
    setFieldErrors({});
    setFormError(null);
    setPending(true);
    try {
      await onSubmit(parsed.data);
      onSuccess?.();
    } catch (error: unknown) {
      setFormError(describeError(error));
    } finally {
      setPending(false);
    }
  }

  const emailErrorId = `${id}-email-error`;
  const passwordErrorId = `${id}-password-error`;

  return (
    <form
      noValidate
      aria-busy={pending}
      onSubmit={(e) => void handleSubmit(e)}
      className="grid gap-4"
    >
      {formError !== null && (
        <p
          role="alert"
          className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
        >
          {formError}
        </p>
      )}
      <div className="grid gap-2">
        <Label htmlFor={`${id}-email`}>Email</Label>
        <Input
          id={`${id}-email`}
          name="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          aria-invalid={fieldErrors.email !== undefined}
          aria-describedby={fieldErrors.email !== undefined ? emailErrorId : undefined}
        />
        {fieldErrors.email !== undefined && (
          <p id={emailErrorId} className="text-destructive text-sm">
            {fieldErrors.email}
          </p>
        )}
      </div>
      <div className="grid gap-2">
        <Label htmlFor={`${id}-password`}>Password</Label>
        <Input
          id={`${id}-password`}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={fieldErrors.password !== undefined}
          aria-describedby={fieldErrors.password !== undefined ? passwordErrorId : undefined}
        />
        {fieldErrors.password !== undefined && (
          <p id={passwordErrorId} className="text-destructive text-sm">
            {fieldErrors.password}
          </p>
        )}
      </div>
      <Button type="submit" disabled={pending} className="w-full">
        {pending && <Loader2 className="animate-spin" aria-hidden="true" />}
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
