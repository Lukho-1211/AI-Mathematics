import assert from "node:assert/strict";
import { latestJobByStage, resolveStepStates } from "./progressChecklist.ts";

function stateMap(opts: Parameters<typeof resolveStepStates>[0]) {
  return Object.fromEntries(resolveStepStates(opts).map((r) => [r.key, r.state]));
}

// Stale PENDING SCENES + VOICE running → SCENES must be done
{
  const states = stateMap({
    stage: "VOICE",
    status: "NARRATION_GENERATED",
    jobs: [
      { stage: "SCRIPT", status: "COMPLETED", progress_percent: 100, created_at: "2026-01-01T00:00:00Z" },
      { stage: "SCENES", status: "PENDING", progress_percent: 0, created_at: "2026-01-01T00:00:00Z" },
      { stage: "SCENES", status: "COMPLETED", progress_percent: 100, created_at: "2026-01-01T00:05:00Z" },
      { stage: "VOICE", status: "RUNNING", progress_percent: 40, created_at: "2026-01-01T00:06:00Z" },
    ],
  });
  assert.equal(states.SCRIPT, "done");
  assert.equal(states.SCENES, "done");
  assert.equal(states.VOICE, "active");
  assert.equal(states.MATHVIZ, "pending");
}

// progress_stage SCENES + RUNNING job → active
{
  const states = stateMap({
    stage: "SCENES",
    status: "SCRIPT_GENERATED",
    jobs: [
      { stage: "SCRIPT", status: "COMPLETED", progress_percent: 100 },
      { stage: "SCENES", status: "RUNNING", progress_percent: 30 },
    ],
  });
  assert.equal(states.SCENES, "active");
  assert.equal(states.SCRIPT, "done");
}

// latestJobByStage prefers newest created_at
{
  const job = latestJobByStage(
    [
      { stage: "SCENES", status: "PENDING", progress_percent: 0, created_at: "2026-01-01T00:00:00Z" },
      { stage: "SCENES", status: "COMPLETED", progress_percent: 100, created_at: "2026-01-01T00:10:00Z" },
    ],
    "SCENES"
  );
  assert.equal(job?.status, "COMPLETED");
}

console.log("progressChecklist tests passed");
