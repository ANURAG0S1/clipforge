const EXTENSION_TYPES: Readonly<Record<string, string>> = {
  mp4: "video/mp4",
  m4v: "video/x-m4v",
  mov: "video/quicktime",
  mkv: "video/x-matroska",
  webm: "video/webm",
  avi: "video/x-msvideo",
  mpg: "video/mpeg",
  mpeg: "video/mpeg",
  ts: "video/mp2t",
};

/**
 * The browser's MIME type when it is a video type, else one inferred from the extension
 * (some browsers report "" for .mkv/.ts). Returns null for anything that is not a video.
 */
export function videoContentType(file: Pick<File, "name" | "type">): string | null {
  if (file.type.startsWith("video/")) return file.type;
  if (file.type !== "" && file.type !== "application/octet-stream") return null;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return EXTENSION_TYPES[ext] ?? null;
}
