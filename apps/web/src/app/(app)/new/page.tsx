import type { Metadata } from "next";

import { NewProjectForm } from "@/components/projects/new-project-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = { title: "New project" };

export default function NewProjectPage() {
  return (
    <Card className="mx-auto w-full max-w-2xl">
      <CardHeader>
        <CardTitle>New project</CardTitle>
        <CardDescription>
          Upload a long video or paste a link. We&apos;ll transcribe it and find the best clips.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <NewProjectForm />
      </CardContent>
    </Card>
  );
}
