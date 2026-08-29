"use client";

import { ProjectStatus } from "@/lib/api";

const COLORS: Record<string, string> = {
  CREATED: "bg-slate-500/20 text-slate-300",
  UPLOADED: "bg-sky-500/20 text-sky-300",
  PROCESSING: "bg-amber-500/20 text-amber-200",
  OCR_COMPLETE: "bg-violet-500/20 text-violet-200",
  AWAITING_REVIEW: "bg-orange-500/20 text-orange-200",
  ANALYZING: "bg-indigo-500/20 text-indigo-200",
  SCRIPT_GENERATED: "bg-cyan-500/20 text-cyan-200",
  VISUALIZING: "bg-fuchsia-500/20 text-fuchsia-200",
  NARRATION_GENERATED: "bg-teal-500/20 text-teal-200",
  RENDERING: "bg-blue-500/20 text-blue-200",
  COMPLETED: "bg-emerald-500/20 text-emerald-200",
  FAILED: "bg-red-500/20 text-red-200",
};

export function StatusBadge({ status }: { status: ProjectStatus | string }) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${
        COLORS[status] || COLORS.CREATED
      }`}
    >
      {String(status).replace(/_/g, " ")}
    </span>
  );
}
