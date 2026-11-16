"use client";

import type { ProjectOut } from "@clipforge/shared-types";
import { AlertCircle, Link2, Loader2, Trash2, Upload } from "lucide-react";
import { useState } from "react";

import { STATUS_LABEL, STATUS_VARIANT } from "@/components/projects/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { formatDuration, isProcessing } from "@/lib/projects";

export interface ProjectCardProps {
  project: ProjectOut;
  onDelete: (id: string) => Promise<void>;
}

export function ProjectCard({ project, onDelete }: ProjectCardProps) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const processing = isProcessing(project);
  const SourceIcon = project.source_type === "url" ? Link2 : Upload;
  const headingId = `project-${project.id}-title`;

  async function handleDelete(): Promise<void> {
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDelete(project.id);
    } catch {
      setDeleteError("Could not delete this project. Try again.");
      setDeleting(false);
      setConfirming(false);
    }
  }

  return (
    <Card className="flex flex-col gap-3 p-4" aria-labelledby={headingId}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 id={headingId} className="truncate font-medium" title={project.title}>
            {project.title}
          </h2>
          <p className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span className="inline-flex items-center gap-1">
              <SourceIcon aria-hidden="true" className="size-3" />
              {project.source_type === "url" ? "Link" : "Upload"}
            </span>
            <span>{formatDuration(project.duration_s)}</span>
            {project.width !== null && project.height !== null && (
              <span>
                {project.width}×{project.height}
                {project.fps !== null && project.fps > 0 ? ` · ${Math.round(project.fps)} fps` : ""}
              </span>
            )}
            <time dateTime={project.created_at}>
              {new Date(project.created_at).toLocaleDateString()}
            </time>
          </p>
        </div>
        <Badge variant={STATUS_VARIANT[project.status]}>
          {processing && <Loader2 aria-hidden="true" className="size-3 animate-spin" />}
          {STATUS_LABEL[project.status]}
        </Badge>
      </div>

      {processing && (
        <Progress
          value={project.progress}
          aria-label={`${STATUS_LABEL[project.status]} progress`}
        />
      )}

      {project.status === "failed" && project.error !== null && (
        <p className="text-destructive flex items-start gap-2 text-sm">
          <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{project.error}</span>
        </p>
      )}
      {deleteError !== null && (
        <p role="alert" className="text-destructive text-sm">
          {deleteError}
        </p>
      )}

      <div className="flex justify-end gap-2">
        {confirming ? (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirming(false)}
              disabled={deleting}
            >
              Keep
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => void handleDelete()}
              disabled={deleting}
            >
              {deleting && <Loader2 aria-hidden="true" className="animate-spin" />}
              Delete project and files
            </Button>
          </>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setConfirming(true)}
            aria-label={`Delete ${project.title}`}
          >
            <Trash2 aria-hidden="true" />
            Delete
          </Button>
        )}
      </div>
    </Card>
  );
}
