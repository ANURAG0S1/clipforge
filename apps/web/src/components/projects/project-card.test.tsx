import type { ProjectOut } from "@clipforge/shared-types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProjectCard } from "./project-card";

function project(overrides: Partial<ProjectOut> = {}): ProjectOut {
  return {
    id: "p1",
    title: "Episode 42",
    source_type: "upload",
    source_url: null,
    duration_s: 301,
    width: 1920,
    height: 1080,
    fps: 29.97,
    status: "ingesting",
    error: null,
    progress: 40,
    created_at: "2026-11-16T10:00:00Z",
    updated_at: "2026-11-16T10:00:00Z",
    ...overrides,
  };
}

describe("ProjectCard", () => {
  it("shows status, metadata and a progress bar while processing", () => {
    render(<ProjectCard project={project()} onDelete={vi.fn(async () => {})} />);
    expect(screen.getByText("Importing")).toBeInTheDocument();
    expect(screen.getByText("5:01")).toBeInTheDocument();
    expect(screen.getByText(/1920×1080 · 30 fps/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Importing progress" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
  });

  it("shows the failure reason and no progress bar when failed", () => {
    render(
      <ProjectCard
        project={project({ status: "failed", error: "Video is too long" })}
        onDelete={vi.fn(async () => {})}
      />,
    );
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Video is too long")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("requires confirmation before deleting and surfaces errors", async () => {
    const onDelete = vi.fn(async () => {
      throw new Error("nope");
    });
    render(<ProjectCard project={project()} onDelete={onDelete} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete Episode 42" }));
    expect(onDelete).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete project and files" }));
    expect(onDelete).toHaveBeenCalledWith("p1");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not delete");
  });
});
