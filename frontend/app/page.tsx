"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Download, Film, Loader2, Plus, AlertCircle, Trash2 } from "lucide-react";
import { api, ProjectSummary } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

const TERMS = [1, 2, 3, 4] as const;
const WEEKS = Array.from({ length: 14 }, (_, i) => i + 1);

type WeekGroup = {
  week: number;
  projects: ProjectSummary[];
};

type TermGroup = {
  term: number;
  weeks: WeekGroup[];
};

/** Object path without query string — used to keep img src stable across poll refreshes. */
function objectPath(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.split("?")[0] ?? null;
}

function mergeProjects(
  prev: ProjectSummary[],
  next: ProjectSummary[]
): ProjectSummary[] {
  const prevById = new Map(prev.map((p) => [p.id, p]));
  return next.map((p) => {
    const old = prevById.get(p.id);
    if (
      old?.thumbnail_url &&
      p.thumbnail_url &&
      objectPath(old.thumbnail_url) === objectPath(p.thumbnail_url)
    ) {
      return { ...p, thumbnail_url: old.thumbnail_url };
    }
    return p;
  });
}

function ProjectCard({
  project: p,
  deletingId,
  onDelete,
  meta,
}: {
  project: ProjectSummary;
  deletingId: string | null;
  onDelete: (e: React.MouseEvent, p: ProjectSummary) => void;
  meta: string;
}) {
  return (
    <div className="panel group relative overflow-hidden transition hover:border-accent/40">
      <Link href={`/projects/${p.id}`} className="block">
        <div className="relative aspect-video overflow-hidden bg-ink-800">
          {p.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={p.thumbnail_url}
              alt={p.title}
              className="absolute inset-0 h-full w-full object-contain"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-slate-600">
              <Film size={32} />
            </div>
          )}
          <div className="absolute left-2 top-2 z-10">
            <StatusBadge status={p.status} />
          </div>
        </div>
        <div className="space-y-2 p-4">
          <h3 className="line-clamp-1 font-semibold group-hover:text-accent-soft">{p.title}</h3>
          <div className="text-xs text-slate-400">{meta}</div>
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>{new Date(p.created_at).toLocaleString()}</span>
            <span>{p.progress_percent}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${p.progress_percent}%` }}
            />
          </div>
          {p.has_video && (
            <div className="flex items-center gap-1 text-xs text-emerald-300">
              <Download size={12} /> Ready to download
            </div>
          )}
          {p.error_message && (
            <div className="line-clamp-2 text-xs text-red-300">{p.error_message}</div>
          )}
        </div>
      </Link>
      <button
        type="button"
        aria-label={`Delete ${p.title}`}
        title="Delete project"
        disabled={deletingId === p.id}
        onClick={(e) => onDelete(e, p)}
        className="absolute right-2 top-2 z-20 rounded-lg border border-white/15 bg-ink-950/80 p-1.5 text-slate-300 opacity-90 backdrop-blur transition hover:border-red-500/50 hover:bg-red-500/20 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {deletingId === p.id ? (
          <Loader2 className="animate-spin" size={14} />
        ) : (
          <Trash2 size={14} />
        )}
      </button>
    </div>
  );
}

export default function DashboardPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [selectedTerm, setSelectedTerm] = useState<number | null>(null);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(null);

  const load = async () => {
    try {
      setError(null);
      const data = await api.listProjects();
      setProjects((prev) => mergeProjects(prev, data));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load projects");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const filteredProjects = useMemo(
    () =>
      projects.filter((project) => {
        if (selectedTerm !== null && project.term !== selectedTerm) return false;
        if (selectedWeek !== null && project.week !== selectedWeek) return false;
        return true;
      }),
    [projects, selectedTerm, selectedWeek]
  );

  const groupedProjects = useMemo<TermGroup[]>(() => {
    return TERMS.map((term) => {
      const termProjects = filteredProjects.filter((project) => project.term === term);
      const weeks = WEEKS.map((week) => ({
        week,
        projects: termProjects.filter((project) => project.week === week),
      })).filter((group) => group.projects.length > 0);

      return { term, weeks };
    }).filter((group) => group.weeks.length > 0);
  }, [filteredProjects]);

  const uncategorizedProjects = useMemo(
    () => filteredProjects.filter((project) => project.term == null || project.week == null),
    [filteredProjects]
  );

  const handleDelete = async (e: React.MouseEvent, p: ProjectSummary) => {
    e.preventDefault();
    e.stopPropagation();
    if (deletingId) return;
    if (!window.confirm(`Delete “${p.title}”? This cannot be undone.`)) return;

    setDeletingId(p.id);
    setError(null);
    try {
      await api.deleteProject(p.id);
      setProjects((prev) => prev.filter((x) => x.id !== p.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete project");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl text-white">Your lessons</h1>
          <p className="mt-1 max-w-xl text-slate-400">
            Upload a scanned mathematics textbook page and MathViz turns it into a narrated,
            animated explanation video.
          </p>
        </div>
        <Link href="/create" className="btn-primary">
          <Plus size={16} /> New Video
        </Link>
      </div>

      <div className="panel flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-slate-300">Term</span>
          <button
            type="button"
            onClick={() => setSelectedTerm(null)}
            className={`rounded-lg px-3 py-1.5 text-sm transition ${
              selectedTerm === null
                ? "bg-accent text-black"
                : "bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            All
          </button>
          {TERMS.map((term) => (
            <button
              key={term}
              type="button"
              onClick={() => setSelectedTerm(term)}
              className={`rounded-lg px-3 py-1.5 text-sm transition ${
                selectedTerm === term
                  ? "bg-accent text-black"
                  : "bg-white/5 text-slate-300 hover:bg-white/10"
              }`}
            >
              Term {term}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-slate-300" htmlFor="week-filter">
            Week
          </label>
          <select
            id="week-filter"
            className="input max-w-[160px] py-1.5"
            value={selectedWeek ?? ""}
            onChange={(e) => setSelectedWeek(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">All weeks</option>
            {WEEKS.map((week) => (
              <option key={week} value={week}>
                Week {week}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="panel flex items-start gap-3 border-red-500/30 p-4 text-red-200">
          <AlertCircle className="mt-0.5 shrink-0" size={18} />
          <div>
            <div className="font-semibold">Could not reach the API</div>
            <div className="text-sm opacity-90">{error}</div>
            <div className="mt-1 text-xs text-red-200/70">
              Ensure Docker services are running (`docker compose up -d postgres redis minio api worker`).
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-slate-400">
          <Loader2 className="animate-spin" size={18} /> Loading projects…
        </div>
      ) : projects.length === 0 ? (
        <div className="panel flex flex-col items-center gap-4 px-6 py-16 text-center">
          <Film className="text-accent" size={40} />
          <div>
            <h2 className="font-display text-xl">No videos yet</h2>
            <p className="mt-1 text-slate-400">
              Start with a scanned page containing something like{" "}
              <code className="text-accent-warm">x² − 5x + 6 = 0</code>
            </p>
          </div>
          <Link href="/create" className="btn-primary">
            Create your first video
          </Link>
        </div>
      ) : filteredProjects.length === 0 ? (
        <div className="panel px-6 py-16 text-center text-slate-400">
          No videos match the selected term/week filters.
        </div>
      ) : (
        <div className="space-y-8">
          {groupedProjects.map((termGroup) => (
            <section key={termGroup.term} className="space-y-4">
              <h2 className="font-display text-xl text-white">Term {termGroup.term}</h2>

              {termGroup.weeks.map((weekGroup) => (
                <div key={weekGroup.week} className="space-y-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-accent-soft">
                    Week {weekGroup.week}
                  </h3>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {weekGroup.projects.map((p) => (
                      <ProjectCard
                        key={p.id}
                        project={p}
                        deletingId={deletingId}
                        onDelete={handleDelete}
                        meta={`Term ${p.term} · Week ${p.week}`}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </section>
          ))}

          {uncategorizedProjects.length > 0 && (
            <section className="space-y-3">
              <h2 className="font-display text-xl text-white">Uncategorized</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {uncategorizedProjects.map((p) => (
                  <ProjectCard
                    key={p.id}
                    project={p}
                    deletingId={deletingId}
                    onDelete={handleDelete}
                    meta={`${p.term != null ? `Term ${p.term}` : "No term"} · ${
                      p.week != null ? `Week ${p.week}` : "No week"
                    }`}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
