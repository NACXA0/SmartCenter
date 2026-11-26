import { STATUS_LABEL, statusTone } from "@/lib/status";
import type { FaceStatus } from "@/api/client";

export function StatusBadge({ status }: { status?: FaceStatus }) {
  const st = status || "none";
  const tone = statusTone(st);
  const soft = st === "accepted";
  return (
    <span className={`badge ${tone}${soft ? " soft" : ""}`}>
      <i />
      <span>{STATUS_LABEL[st] || st}</span>
    </span>
  );
}
