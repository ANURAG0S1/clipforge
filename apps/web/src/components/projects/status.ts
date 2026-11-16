import type { ProjectStatus } from "@clipforge/shared-types";

import type { BadgeProps } from "@/components/ui/badge";

export const STATUS_LABEL: Record<ProjectStatus, string> = {
  pending: "Queued",
  ingesting: "Importing",
  transcribing: "Transcribing",
  analyzing: "Finding clips",
  ready: "Ready",
  failed: "Failed",
};

export const STATUS_VARIANT: Record<ProjectStatus, NonNullable<BadgeProps["variant"]>> = {
  pending: "outline",
  ingesting: "secondary",
  transcribing: "secondary",
  analyzing: "secondary",
  ready: "success",
  failed: "destructive",
};
