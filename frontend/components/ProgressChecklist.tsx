"use client";

import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";

const STEPS = [
  { key: "UPLOAD", label: "Uploading" },
  { key: "OCR", label: "Reading textbook" },
  { key: "REVIEW", label: "Human verification" },
  { key: "UNDERSTANDING", label: "Understanding mathematics" },
  { key: "SCRIPT", label: "Creating explanation" },
  { key: "SCENES", label: "Creating scene specs" },
  { key: "VOICE", label: "Generating narration" },
  { key: "MATHVIZ", label: "Creating MathVizAI scenes" },
  { key: "RENDER", label: "Rendering video" },
  { key: "FINALIZE", label: "Finalizing" },
  { key: "COMPLETED", label: "Complete" },
];

const ORDER = STEPS.map((s) => s.key);

export function ProgressChecklist({
  stage,
  percent,
  status,
  jobs,
}: {
  stage?: string | null;
  percent: number;
  status: string;
  jobs: Array<{ stage: string; status: string; progress_percent: number; message?: string | null }>;
}) {
  const currentIdx = Math.max(0, ORDER.indexOf((stage || "UPLOAD").toUpperCase()));
  const failed = status === "FAILED";

  return (
    <div className="panel space-y-3 p-5">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg">Generation progress</h3>
        <span className="text-sm text-slate-400">{percent}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full transition-all ${failed ? "bg-red-400" : "bg-accent"}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <ul className="space-y-2">
        {STEPS.map((step, idx) => {
          const job = jobs.find((j) => j.stage === step.key);
          let state: "done" | "active" | "pending" | "failed" = "pending";
          if (failed && idx === currentIdx) state = "failed";
          else if (status === "COMPLETED" || idx < currentIdx) state = "done";
          else if (idx === currentIdx) state = "active";
          if (job?.status === "COMPLETED") state = "done";
          if (job?.status === "FAILED") state = "failed";
          if (job?.status === "RUNNING") state = "active";

          const Icon =
            state === "done"
              ? CheckCircle2
              : state === "failed"
                ? XCircle
                : state === "active"
                  ? Loader2
                  : Circle;

          return (
            <li key={step.key} className="flex items-center gap-3 text-sm">
              <Icon
                size={16}
                className={
                  state === "done"
                    ? "text-emerald-400"
                    : state === "failed"
                      ? "text-red-400"
                      : state === "active"
                        ? "animate-spin text-accent"
                        : "text-slate-600"
                }
              />
              <span className={state === "pending" ? "text-slate-500" : "text-slate-200"}>
                {step.label}
              </span>
              {state === "active" && job?.progress_percent != null && (
                <span className="ml-auto text-xs text-slate-400">{job.progress_percent}%</span>
              )}
              {state === "done" && <span className="ml-auto text-xs text-emerald-400/80">✓</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
