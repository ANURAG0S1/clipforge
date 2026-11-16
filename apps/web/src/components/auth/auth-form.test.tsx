import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import { AuthForm } from "./auth-form";

describe("AuthForm", () => {
  it("shows field errors and does not submit invalid input", async () => {
    const onSubmit = vi.fn<(c: { email: string; password: string }) => Promise<void>>();
    render(<AuthForm onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByText("Enter a valid email address")).toBeInTheDocument();
    expect(screen.getByText("Password must be at least 8 characters")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits trimmed credentials and calls onSuccess", async () => {
    const onSubmit = vi.fn(async () => {});
    const onSuccess = vi.fn();
    render(<AuthForm onSubmit={onSubmit} onSuccess={onSuccess} />);

    await userEvent.type(screen.getByLabelText("Email"), "  dana@example.com ");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(onSubmit).toHaveBeenCalledWith({ email: "dana@example.com", password: "correct horse" });
    expect(onSuccess).toHaveBeenCalledOnce();
  });

  it("maps a 401 to a friendly alert", async () => {
    const onSubmit = vi.fn(async () => {
      throw new ApiError(401, "Invalid credentials");
    });
    render(<AuthForm onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Email"), "dana@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("uses register copy and maps 409 to a sign-in hint", async () => {
    const onSubmit = vi.fn(async () => {
      throw new ApiError(409, "exists");
    });
    render(<AuthForm mode="register" onSubmit={onSubmit} />);
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "new-password");

    await userEvent.type(screen.getByLabelText("Email"), "dana@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  });
});
