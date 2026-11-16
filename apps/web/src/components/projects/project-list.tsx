"use client";

import type { ProjectOut } from "@clipforge/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, Plus } from "lucide-react";
import Link from "next/link";

import { ProjectCard } from "@/components/projects/project-card";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { deleteProject, isProcessing, listProjects, projectKeys } from "@/lib/projects";

const POLL_MS = 3000;

export function ProjectList() {
  const queryClient = useQueryClient();
  const projects = useQuery({
    queryKey: projectKeys.all,
    queryFn: ({ signal }) => listProjects(signal),
    refetchInterval: (query) => ((query.state.data ?? []).some(isProcessing) ? POLL_MS : false),
  });
  const remove = useMutation({
    mutationFn: deleteProject,
    onSuccess: (_void, id) => {
      queryClient.setQueryData<ProjectOut[]>(projectKeys.all, (old) =>
        (old ?? []).filter((p) => p.id !== id),
      );
    },
  });

  if (projects.isPending) {
    return (
      <div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        aria-busy="true"
        aria-label="Loading projects"
      >
        {[0, 1, 2].map((i) => (
          <Card key={i} className="bg-muted/50 h-32 animate-pulse" />
        ))}
      </div>
    );
  }

  if (projects.isError) {
    return (
      <Card className="flex flex-col items-center gap-3 p-8 text-center">
        <p role="alert" className="text-muted-foreground text-sm">
          Couldn&apos;t load your projects.
        </p>
        <Button variant="outline" onClick={() => void projects.refetch()}>
          Try again
        </Button>
      </Card>
    );
  }

  if (projects.data.length === 0) {
    return (
      <Card className="flex flex-col items-center gap-3 p-10 text-center">
        <Film aria-hidden="true" className="text-muted-foreground size-10" />
        <h2 className="font-medium">No projects yet</h2>
        <p className="text-muted-foreground max-w-sm text-sm">
          Upload a long video or paste a link, and ClipForge will find the best moments for
          short-form clips.
        </p>
        <Button asChild>
          <Link href="/new">
            <Plus aria-hidden="true" />
            New project
          </Link>
        </Button>
      </Card>
    );
  }

  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {projects.data.map((project) => (
        <li key={project.id}>
          <ProjectCard project={project} onDelete={(id) => remove.mutateAsync(id)} />
        </li>
      ))}
    </ul>
  );
}
