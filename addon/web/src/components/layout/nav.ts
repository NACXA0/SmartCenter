import { LayoutDashboard, Camera, Library, Activity } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type NavId = "overview" | "capture" | "gallery" | "audit";

/** Add-on 职责 → 导航：概览统计 / 采集 / 人脸库 / 审计（开门全自动无专页） */
export const NAV: { id: NavId; label: string; path: string; icon: LucideIcon }[] = [
  { id: "overview", label: "概览", path: "/overview", icon: LayoutDashboard },
  { id: "capture", label: "采集", path: "/capture", icon: Camera },
  { id: "gallery", label: "人脸库", path: "/gallery", icon: Library },
  { id: "audit", label: "审计", path: "/audit", icon: Activity },
];
