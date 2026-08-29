"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Download, Film, Loader2, Plus, AlertCircle } from "lucide-react";
import { api, ProjectSummary } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

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

export default function DashboardPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <Link
              key={p.id}
              href={`/projects/${p.id}`}
              className="panel group overflow-hidden transition hover:border-accent/40"
            >
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
                <h3 className="line-clamp-1 font-semibold group-hover:text-accent-soft">
                  {p.title}
                </h3>
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
          ))}
        </div>
      )}
    </div>
  );
}
