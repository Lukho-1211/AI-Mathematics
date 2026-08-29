"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  Download,
  Loader2,
  RefreshCw,
  Sparkles,
  Check,
} from "lucide-react";
import { api, MathExpression, ProjectDetail } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { LatexView } from "@/components/LatexView";
import { ProgressChecklist } from "@/components/ProgressChecklist";

export default function ProjectPage() {
  const params = useParams();
  const id = params.id as string;
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, MathExpression>>({});

  const load = useCallback(async () => {
    try {
      const data = await api.getProject(id);
      setProject(data);
      setEdits(Object.fromEntries(data.expressions.map((e) => [e.id, { ...e }])));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load project");
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while processing
  useEffect(() => {
    if (!project) return;
    const active = [
      "PROCESSING",
      "ANALYZING",
      "SCRIPT_GENERATED",
      "VISUALIZING",
      "NARRATION_GENERATED",
      "RENDERING",
    ].includes(project.status);
    if (!active) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [project?.status, load]);

  // SSE progress
  useEffect(() => {
    if (!id) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(api.progressUrl(id));
      es.addEventListener("progress", () => {
        load();
      });
    } catch {
      /* polling fallback */
    }
    return () => es?.close();
  }, [id, load]);

  const needsReview = useMemo(
    () => Object.values(edits).filter((e) => e.needs_review),
    [edits]
  );

  const primaryVideo = project?.videos.find((v) => v.is_primary) || project?.videos[0];

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  };

  if (!project && !error) {
    return (
      <div className="flex items-center gap-2 text-slate-400">
        <Loader2 className="animate-spin" /> Loading project…
      </div>
    );
  }

  if (!project) {
    return <div className="text-red-300">{error}</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <StatusBadge status={project.status} />
            <span className="text-xs text-slate-500">{project.id}</span>
          </div>
          <h1 className="font-display text-3xl">{project.title}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={() => load()} disabled={!!busy}>
            <RefreshCw size={14} /> Refresh
          </button>
          {project.status === "UPLOADED" && (
            <button
              className="btn-primary"
              disabled={!!busy}
              onClick={() => run("ocr", () => api.startOcr(project.id))}
            >
              {busy === "ocr" ? <Loader2 className="animate-spin" size={14} /> : <Sparkles size={14} />}
              Analyze Page
            </button>
          )}
          {(project.status === "OCR_COMPLETE" || project.status === "AWAITING_REVIEW") &&
            project.ocr_reviewed && (
              <button
                className="btn-primary"
                disabled={!!busy}
                onClick={() =>
                  run("generate", () =>
                    api.generate(project.id, {
                      voice_gender: project.voice_gender,
                      voice_speed: project.voice_speed,
                      language: project.language,
                    })
                  )
                }
              >
                {busy === "generate" ? (
                  <Loader2 className="animate-spin" size={14} />
                ) : (
                  <Sparkles size={14} />
                )}
                Generate Explanation Video
              </button>
            )}
          {primaryVideo?.url && (
            <a
              className="btn-primary"
              href={api.videoDownloadUrl(project.id, "1080p")}
              download
            >
              <Download size={14} /> Download MP4
            </a>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
          {error}
        </div>
      )}
      {project.error_message && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
          <strong>Pipeline error:</strong> {project.error_message}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* Uploaded page */}
          <section className="panel p-5">
            <h2 className="font-display text-xl">Uploaded page</h2>
            <div className="mt-3 overflow-hidden rounded-xl bg-black/40">
              {project.uploaded_page_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={project.uploaded_page_url}
                  alt="Textbook page"
                  className="mx-auto max-h-[480px] object-contain"
                />
              ) : (
                <div className="p-10 text-center text-slate-500">No page uploaded</div>
              )}
            </div>
          </section>

          {/* OCR Review */}
          <section className="panel space-y-4 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="font-display text-xl">Extracted mathematics</h2>
                <p className="text-sm text-slate-400">
                  Review and correct before generating. Flagged items must be fixed — the system
                  will not invent mathematics.
                </p>
              </div>
              {(project.status === "AWAITING_REVIEW" || project.status === "OCR_COMPLETE") &&
                !project.ocr_reviewed && (
                  <button
                    className="btn-primary"
                    disabled={!!busy || needsReview.length > 0}
                    onClick={() =>
                      run("approve", () =>
                        api.approveReview(
                          project.id,
                          Object.values(edits).map((e) => ({
                            id: e.id,
                            original_text: e.original_text,
                            latex: e.latex,
                            element_type: e.element_type,
                          }))
                        )
                      )
                    }
                  >
                    {busy === "approve" ? (
                      <Loader2 className="animate-spin" size={14} />
                    ) : (
                      <Check size={14} />
                    )}
                    Approve & continue
                  </button>
                )}
            </div>

            {needsReview.length > 0 && (
              <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                {needsReview.length} item(s) need verification due to low OCR confidence.
              </div>
            )}

            {project.expressions.length === 0 ? (
              <p className="text-sm text-slate-500">
                No expressions yet. Upload a page and click Analyze.
              </p>
            ) : (
              <div className="space-y-3">
                {Object.values(edits)
                  .sort((a, b) => a.order_index - b.order_index)
                  .map((expr) => (
                    <div
                      key={expr.id}
                      className={`rounded-xl border p-4 ${
                        expr.needs_review
                          ? "border-amber-500/40 bg-amber-500/5"
                          : "border-white/10 bg-ink-800/50"
                      }`}
                    >
                      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                        <span className="rounded bg-white/10 px-2 py-0.5 uppercase">
                          {expr.element_type}
                        </span>
                        <span>confidence {(expr.confidence * 100).toFixed(0)}%</span>
                        {expr.needs_review && (
                          <span className="text-amber-300">needs review</span>
                        )}
                      </div>
                      <label className="label">Detected text</label>
                      <textarea
                        className="input mb-3 min-h-[60px]"
                        value={expr.original_text}
                        disabled={project.ocr_reviewed}
                        onChange={(e) =>
                          setEdits((prev) => ({
                            ...prev,
                            [expr.id]: {
                              ...expr,
                              original_text: e.target.value,
                              needs_review: false,
                            },
                          }))
                        }
                      />
                      <label className="label">LaTeX</label>
                      <input
                        className="input mb-3 font-mono text-xs"
                        value={expr.latex || ""}
                        disabled={project.ocr_reviewed}
                        onChange={(e) =>
                          setEdits((prev) => ({
                            ...prev,
                            [expr.id]: {
                              ...expr,
                              latex: e.target.value,
                              needs_review: false,
                            },
                          }))
                        }
                      />
                      {expr.latex && (
                        <div className="rounded-lg bg-black/30 p-3 text-center">
                          <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
                            Rendered
                          </div>
                          <LatexView latex={expr.latex} block />
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </section>

          {/* Lesson / script / scenes */}
          {project.lesson_plan && (
            <section className="panel space-y-3 p-5">
              <h2 className="font-display text-xl">Lesson plan</h2>
              <p className="text-accent-soft">{project.lesson_plan.topic}</p>
              <div>
                <h3 className="text-sm font-semibold text-slate-300">Objectives</h3>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-400">
                  {project.lesson_plan.learning_objectives.map((o, i) => (
                    <li key={i}>{o}</li>
                  ))}
                </ul>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {project.lesson_plan.sections.map((s, i) => (
                  <div key={i} className="rounded-lg bg-ink-800 px-3 py-2 text-sm">
                    <div className="font-medium">{s.title}</div>
                    <div className="text-xs text-slate-500">{s.duration}s</div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {project.script && (
            <section className="panel space-y-3 p-5">
              <h2 className="font-display text-xl">Narration script</h2>
              <pre className="whitespace-pre-wrap rounded-xl bg-ink-800/80 p-4 text-sm leading-relaxed text-slate-300">
                {project.script.full_script}
              </pre>
            </section>
          )}

          {project.scenes.length > 0 && (
            <section className="panel space-y-3 p-5">
              <h2 className="font-display text-xl">Scenes</h2>
              <div className="space-y-2">
                {project.scenes.map((s) => (
                  <details key={s.id} className="rounded-xl border border-white/10 bg-ink-800/40 p-3">
                    <summary className="cursor-pointer font-medium">
                      {s.scene_id} · {s.title}{" "}
                      <span className="text-xs text-slate-500">
                        ({s.scene_type}, {(s.duration_actual || s.duration_target).toFixed(1)}s)
                      </span>
                    </summary>
                    <p className="mt-2 text-sm text-slate-400">{s.narration}</p>
                    <pre className="mt-2 overflow-auto rounded bg-black/30 p-2 text-[11px] text-slate-500">
                      {JSON.stringify(s.visualization_spec, null, 2)}
                    </pre>
                  </details>
                ))}
              </div>
            </section>
          )}

          {/* Video player */}
          {primaryVideo?.url && (
            <section className="panel space-y-3 p-5">
              <h2 className="font-display text-xl">Video preview</h2>
              <video
                key={primaryVideo.url}
                controls
                className="w-full rounded-xl bg-black"
                src={primaryVideo.url}
              />
              <div className="flex flex-wrap gap-2">
                <a
                  className="btn-primary"
                  href={api.videoDownloadUrl(project.id, "1080p")}
                  download
                >
                  <Download size={14} /> Download 1080p MP4
                </a>
                <a
                  className="btn-secondary"
                  href={api.videoDownloadUrl(project.id, "720p")}
                  download
                >
                  Download 720p
                </a>
                <a
                  className="btn-secondary"
                  href={api.subtitleUrl(project.id, "srt")}
                  download
                >
                  Download SRT
                </a>
                <a
                  className="btn-secondary"
                  href={api.subtitleUrl(project.id, "vtt")}
                  download
                >
                  Download VTT
                </a>
                <a className="btn-secondary" href={api.lessonUrl(project.id)} download>
                  Download lesson
                </a>
              </div>
            </section>
          )}
        </div>

        <div className="space-y-6">
          <ProgressChecklist
            stage={project.progress_stage}
            percent={project.progress_percent}
            status={project.status}
            jobs={project.jobs}
          />

          <section className="panel space-y-3 p-5 text-sm">
            <h3 className="font-display text-lg">Voice settings</h3>
            <div className="grid grid-cols-2 gap-2 text-slate-400">
              <div>Gender</div>
              <div className="text-right text-slate-200">{project.voice_gender}</div>
              <div>Speed</div>
              <div className="text-right text-slate-200">{project.voice_speed}</div>
              <div>Language</div>
              <div className="text-right text-slate-200">{project.language}</div>
              <div>Subtitles</div>
              <div className="text-right text-slate-200">
                {project.enable_subtitles ? "On" : "Off"}
              </div>
            </div>
          </section>

          {project.ocr_reviewed &&
            project.status === "OCR_COMPLETE" && (
              <button
                className="btn-primary w-full"
                disabled={!!busy}
                onClick={() =>
                  run("generate", () =>
                    api.generate(project.id, {
                      voice_gender: project.voice_gender,
                      voice_speed: project.voice_speed,
                      language: project.language,
                    })
                  )
                }
              >
                {busy === "generate" ? (
                  <Loader2 className="animate-spin" size={16} />
                ) : (
                  <Sparkles size={16} />
                )}
                Generate Explanation Video
              </button>
            )}
        </div>
      </div>
    </div>
  );
}
