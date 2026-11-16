import { redirect } from "next/navigation";

export default function HomePage(): never {
  // Project list lands here in Phase 2; until auth exists every visitor starts at login.
  redirect("/login");
}
