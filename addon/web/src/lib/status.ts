import type { FaceStatus } from "@/api/client";

export const STATUS_LABEL: Record<string, string> = {
  none: "未采集",
  pending: "待重采",
  accepted: "可开门",
  verified: "已验证",
  rejected: "已停用",
};

export function statusTone(status: FaceStatus): "muted" | "info" | "ok" | "warn" | "danger" {
  switch (status) {
    case "verified":
      return "ok";
    case "accepted":
      return "ok";
    case "pending":
      return "info";
    case "rejected":
      return "danger";
    default:
      return "muted";
  }
}
