"use client";

import { useCallback, useMemo, useState } from "react";
import Cropper, { Area } from "react-easy-crop";
import { useRouter } from "next/navigation";
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  RotateCw,
  Trash2,
  Upload,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";

const ACCEPT = ".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf";
const MAX_PAGES = 10;
const MAX_BYTES = 25 * 1024 * 1024;
const ALLOWED_EXT = new Set(["jpg", "jpeg", "png", "webp", "pdf"]);
const ALLOWED_MIME = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "application/pdf",
]);

type PageItem = {
  id: string;
  file: File;
  previewUrl: string | null;
  isPdf: boolean;
  rotation: number;
  pdfPageNumber: number;
  crop: { x: number; y: number };
  zoom: number;
  croppedArea: Area | null;
};

function isAllowedFile(f: File): boolean {
  const ext = f.name.split(".").pop()?.toLowerCase() || "";
  if (ALLOWED_EXT.has(ext)) return true;
  return ALLOWED_MIME.has((f.type || "").toLowerCase());
}

function makePageItem(f: File): PageItem {
  const isPdf = f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
  return {
    id: `${f.name}-${f.size}-${f.lastModified}-${Math.random().toString(36).slice(2)}`,
    file: f,
    previewUrl: !isPdf && f.type.startsWith("image/") ? URL.createObjectURL(f) : null,
    isPdf,
    rotation: 0,
    pdfPageNumber: 1,
    crop: { x: 0, y: 0 },
    zoom: 1,
    croppedArea: null,
  };
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function cropPayloadFor(page: PageItem): Promise<object | null> {
  if (!page.previewUrl || !page.croppedArea) return null;
  const dims = await new Promise<{ w: number; h: number }>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
    img.onerror = reject;
    img.src = page.previewUrl!;
  });
  return {
    x: page.croppedArea.x / dims.w,
    y: page.croppedArea.y / dims.h,
    width: page.croppedArea.width / dims.w,
    height: page.croppedArea.height / dims.h,
  };
}

export default function CreatePage() {
  const router = useRouter();
  const [pages, setPages] = useState<PageItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [title, setTitle] = useState("Untitled Lesson");
  const [voiceGender, setVoiceGender] = useState("female");
  const [voiceSpeed, setVoiceSpeed] = useState(1);
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const active = useMemo(
    () => pages.find((p) => p.id === activeId) || pages[0] || null,
    [pages, activeId]
  );

  const updateActive = useCallback(
    (patch: Partial<PageItem>) => {
      if (!active) return;
      setPages((prev) => prev.map((p) => (p.id === active.id ? { ...p, ...patch } : p)));
    },
    [active]
  );

  const addFiles = useCallback(
    (fileList: FileList | File[]) => {
      const incoming = Array.from(fileList);
      if (!incoming.length) return;

      const errors: string[] = [];
      const accepted: File[] = [];

      for (const f of incoming) {
        if (!isAllowedFile(f)) {
          errors.push(`${f.name}: unsupported type`);
          continue;
        }
        if (f.size === 0) {
          errors.push(`${f.name}: empty file`);
          continue;
        }
        if (f.size > MAX_BYTES) {
          errors.push(`${f.name}: exceeds 25MB`);
          continue;
        }
        accepted.push(f);
      }

      setPages((prev) => {
        const room = MAX_PAGES - prev.length;
        if (room <= 0) {
          errors.push(`Maximum ${MAX_PAGES} pages per lesson`);
          return prev;
        }
        if (accepted.length > room) {
          errors.push(`Only ${room} more page(s) allowed (max ${MAX_PAGES})`);
        }
        const toAdd = accepted.slice(0, room).map(makePageItem);
        if (!toAdd.length) return prev;

        if ((!title || title === "Untitled Lesson") && prev.length === 0 && toAdd[0]) {
          setTitle(toAdd[0].file.name.replace(/\.[^.]+$/, ""));
        }
        if (!activeId && toAdd[0]) {
          setActiveId(toAdd[0].id);
        }
        return [...prev, ...toAdd];
      });

      setError(errors.length ? errors.join(" · ") : null);
    },
    [activeId, title]
  );

  const removePage = (id: string) => {
    setPages((prev) => {
      const target = prev.find((p) => p.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      const next = prev.filter((p) => p.id !== id);
      if (activeId === id) {
        setActiveId(next[0]?.id || null);
      }
      return next;
    });
  };

  const movePage = (id: string, dir: -1 | 1) => {
    setPages((prev) => {
      const i = prev.findIndex((p) => p.id === id);
      if (i < 0) return prev;
      const j = i + dir;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const onCropComplete = useCallback(
    (_: Area, croppedPixels: Area) => {
      if (!active) return;
      setPages((prev) =>
        prev.map((p) => (p.id === active.id ? { ...p, croppedArea: croppedPixels } : p))
      );
    },
    [active]
  );

  const submit = async (analyzeImmediately: boolean) => {
    if (!pages.length) {
      setError("Please choose at least one textbook page image or PDF");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        title,
        voice_gender: voiceGender,
        voice_speed: voiceSpeed,
        language,
        enable_subtitles: true,
      } as never);

      for (let i = 0; i < pages.length; i++) {
        const page = pages[i];
        const crop = await cropPayloadFor(page);
        await api.upload(project.id, page.file, {
          rotation: page.rotation,
          page_number: page.pdfPageNumber,
          crop,
          replace: i === 0,
        });
      }

      if (analyzeImmediately) {
        await api.startOcr(project.id);
      }
      router.push(`/projects/${project.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl">Create explanation video</h1>
        <p className="mt-1 text-slate-400">
          Step 1 — Upload one or more scanned mathematics textbook pages (JPG, PNG, WEBP, or
          PDF). Multiple pages become one lesson video.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="panel space-y-4 p-5">
          <label className="label">Textbook pages</label>
          <div
            className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border border-dashed px-4 py-10 transition-colors ${
              dragOver
                ? "border-accent bg-accent/10"
                : "border-white/20 bg-ink-800/50 hover:border-accent/50"
            }`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              addFiles(e.dataTransfer.files);
            }}
            onClick={() => document.getElementById("page-file-input")?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                document.getElementById("page-file-input")?.click();
              }
            }}
          >
            <Upload className="text-accent" size={28} />
            <div className="text-center text-sm">
              <div className="font-semibold">Drop pages here or click to browse</div>
              <div className="text-slate-400">
                JPG · JPEG · PNG · WEBP · PDF · max 25MB each · up to {MAX_PAGES} pages
              </div>
            </div>
            <input
              id="page-file-input"
              type="file"
              accept={ACCEPT}
              multiple
              className="hidden"
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {pages.length > 0 && (
            <ul className="space-y-2">
              {pages.map((p, idx) => {
                const selected = active?.id === p.id;
                return (
                  <li
                    key={p.id}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-sm ${
                      selected
                        ? "border-accent/60 bg-accent/10"
                        : "border-white/10 bg-ink-800/40"
                    }`}
                  >
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => setActiveId(p.id)}
                    >
                      <div className="truncate font-medium text-white">
                        {idx + 1}. {p.file.name}
                      </div>
                      <div className="text-xs text-slate-400">{formatSize(p.file.size)}</div>
                    </button>
                    <button
                      type="button"
                      className="btn-secondary !px-2 !py-1"
                      disabled={idx === 0}
                      onClick={() => movePage(p.id, -1)}
                      title="Move up"
                    >
                      <ChevronUp size={14} />
                    </button>
                    <button
                      type="button"
                      className="btn-secondary !px-2 !py-1"
                      disabled={idx === pages.length - 1}
                      onClick={() => movePage(p.id, 1)}
                      title="Move down"
                    >
                      <ChevronDown size={14} />
                    </button>
                    <button
                      type="button"
                      className="btn-secondary !px-2 !py-1"
                      onClick={() => removePage(p.id)}
                      title="Remove"
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {active?.isPdf && (
            <div>
              <label className="label">PDF page number (active file)</label>
              <input
                type="number"
                min={1}
                className="input"
                value={active.pdfPageNumber}
                onChange={(e) =>
                  updateActive({ pdfPageNumber: Number(e.target.value) || 1 })
                }
              />
            </div>
          )}

          <div>
            <label className="label">Lesson title</label>
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="label">Voice</label>
              <select
                className="input"
                value={voiceGender}
                onChange={(e) => setVoiceGender(e.target.value)}
              >
                <option value="female">Female</option>
                <option value="male">Male</option>
              </select>
            </div>
            <div>
              <label className="label">Speed</label>
              <input
                type="number"
                step="0.05"
                min={0.5}
                max={1.5}
                className="input"
                value={voiceSpeed}
                onChange={(e) => setVoiceSpeed(Number(e.target.value))}
              />
            </div>
            <div>
              <label className="label">Language</label>
              <select
                className="input"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
              >
                <option value="en">English</option>
                <option value="es">Spanish</option>
                <option value="fr">French</option>
                <option value="de">German</option>
              </select>
            </div>
          </div>

          {error && <div className="rounded-xl bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}

          <div className="flex flex-wrap gap-2 pt-2">
            <button
              className="btn-secondary"
              disabled={busy || !pages.length}
              onClick={() => submit(false)}
            >
              {busy ? <Loader2 className="animate-spin" size={16} /> : null}
              Upload only
            </button>
            <button
              className="btn-primary"
              disabled={busy || !pages.length}
              onClick={() => submit(true)}
            >
              {busy ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
              Upload & Analyze
            </button>
          </div>
        </div>

        <div className="panel space-y-3 p-5">
          <div className="flex items-center justify-between">
            <label className="label mb-0">
              Preview · crop · rotate
              {active ? ` · page ${pages.findIndex((p) => p.id === active.id) + 1}` : ""}
            </label>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => updateActive({ rotation: ((active?.rotation || 0) + 90) % 360 })}
              disabled={!active?.previewUrl}
            >
              <RotateCw size={14} /> Rotate
            </button>
          </div>
          <div className="relative h-[420px] overflow-hidden rounded-xl bg-black/40">
            {active?.previewUrl ? (
              <Cropper
                image={active.previewUrl}
                crop={active.crop}
                zoom={active.zoom}
                rotation={active.rotation}
                aspect={undefined}
                onCropChange={(crop) => updateActive({ crop })}
                onZoomChange={(zoom) => updateActive({ zoom })}
                onCropComplete={onCropComplete}
              />
            ) : (
              <div className="flex h-full items-center justify-center px-6 text-center text-sm text-slate-500">
                {active?.isPdf
                  ? "PDF selected — page will be rasterized on upload. Preview is available after processing."
                  : pages.length
                    ? "Select an image page to preview and crop."
                    : "Image preview appears here after you select files."}
              </div>
            )}
          </div>
          {active?.previewUrl && (
            <div>
              <label className="label">Zoom</label>
              <input
                type="range"
                min={1}
                max={3}
                step={0.05}
                value={active.zoom}
                onChange={(e) => updateActive({ zoom: Number(e.target.value) })}
                className="w-full"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
