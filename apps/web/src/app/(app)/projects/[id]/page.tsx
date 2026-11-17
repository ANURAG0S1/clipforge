import type { Metadata } from "next";

import { ProjectWorkspace } from "@/components/projects/project-workspace";

export const metadata: Metadata = { title: "Project" };

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function ProjectPage({ params }: PageProps) {
  const { id } = await params;
  return <ProjectWorkspace projectId={id} />;
}
