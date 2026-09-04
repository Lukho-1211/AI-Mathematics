export const PROGRESS_STEPS = [
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
] as const;

export type ProgressStepKey = (typeof PROGRESS_STEPS)[number]["key"];

export type ProgressJob = {
  stage: string;
  status: string;
  progress_percent: number;
  message?: string | null;
  created_at?: string | null;
};

export type StepState = "done" | "active" | "pending" | "failed";

const ORDER = PROGRESS_STEPS.map((s) => s.key);

/** Prefer the newest job row when duplicates exist for a stage. */
export function latestJobByStage(
  jobs: ProgressJob[],
  stage: string
): ProgressJob | undefined {
  const matches = jobs.filter((j) => j.stage === stage);
  if (matches.length === 0) return undefined;
  if (matches.length === 1) return matches[0];
  return matches.reduce((best, cur) => {
    const bt = best.created_at ? Date.parse(best.created_at) : 0;
    const ct = cur.created_at ? Date.parse(cur.created_at) : 0;
    return ct >= bt ? cur : best;
  });
}

/**
 * Resolve checklist states so SCENES (and other middle steps) do not stay
 * pending when a later stage is already running/completed.
 */
export function resolveStepStates(opts: {
  stage?: string | null;
  status: string;
  jobs: ProgressJob[];
}): Array<{ key: ProgressStepKey; state: StepState; job?: ProgressJob }> {
  const currentIdx = Math.max(0, ORDER.indexOf((opts.stage || "UPLOAD").toUpperCase() as ProgressStepKey));
  const failed = opts.status === "FAILED";
  const completed = opts.status === "COMPLETED";

  // Highest index that has a RUNNING or COMPLETED job (drives earlier PENDING → done)
  let farthestActiveOrDone = -1;
  for (let i = 0; i < ORDER.length; i++) {
    const job = latestJobByStage(opts.jobs, ORDER[i]);
    if (job?.status === "RUNNING" || job?.status === "COMPLETED") {
      farthestActiveOrDone = i;
    }
  }

  return PROGRESS_STEPS.map((step, idx) => {
    const job = latestJobByStage(opts.jobs, step.key);
    let state: StepState = "pending";

    if (failed && idx === currentIdx) state = "failed";
    else if (completed || idx < currentIdx) state = "done";
    else if (idx === currentIdx) state = "active";

    // If a later stage has progressed, earlier pending steps are done
    if (state === "pending" && farthestActiveOrDone > idx) {
      state = "done";
    }

    if (job?.status === "COMPLETED") state = "done";
    if (job?.status === "FAILED") state = "failed";
    if (job?.status === "RUNNING") state = "active";

    return { key: step.key, state, job };
  });
}
