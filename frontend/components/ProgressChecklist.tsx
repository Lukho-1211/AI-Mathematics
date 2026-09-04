"use client";

import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { PROGRESS_STEPS, resolveStepStates } from "@/lib/progressChecklist";

export function ProgressChecklist({
  stage,
  percent,
  status,
  jobs,
}: {
  stage?: string | null;
  percent: number;
  status: string;
  jobs: Array<{
    stage: string;
    status: string;
    progress_percent: number;
    message?: string | null;
    created_at?: string | null;
  }>;
}) {
  const failed = status === "FAILED";
  const resolved = resolveStepStates({ stage, status, jobs });

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
        {PROGRESS_STEPS.map((step) => {
          const { state, job } = resolved.find((r) => r.key === step.key) || {
            state: "pending" as const,
            job: undefined,
          };

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
