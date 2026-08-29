"use client";

import { useCallback, useState } from "react";
import Cropper, { Area } from "react-easy-crop";
import { useRouter } from "next/navigation";
import {
  Loader2,
  RotateCw,
  Upload,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";

const ACCEPT = ".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf";

export default function CreatePage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isPdf, setIsPdf] = useState(false);
  const [rotation, setRotation] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [croppedArea, setCroppedArea] = useState<Area | null>(null);
  const [title, setTitle] = useState("Untitled Lesson");
  const [voiceGender, setVoiceGender] = useState("female");
  const [voiceSpeed, setVoiceSpeed] = useState(1);
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onFile = (f: File | null) => {
    if (!f) return;
    setFile(f);
    setIsPdf(f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"));
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    if (f.type.startsWith("image/")) {
      setPreviewUrl(URL.createObjectURL(f));
    } else {
      setPreviewUrl(null);
    }
    if (!title || title === "Untitled Lesson") {
      setTitle(f.name.replace(/\.[^.]+$/, ""));
    }
  };

  const onCropComplete = useCallback((_: Area, croppedPixels: Area) => {
    setCroppedArea(croppedPixels);
  }, []);

  const submit = async (analyzeImmediately: boolean) => {
    if (!file) {
      setError("Please choose a textbook page image or PDF");
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

      let cropPayload: object | null = null;
      if (previewUrl && croppedArea) {
        // Convert pixel crop to normalized using natural image size via cropper media size approximation
        // react-easy-crop gives pixels relative to natural image — we need natural dims.
        // We'll read them from an Image.
        const dims = await new Promise<{ w: number; h: number }>((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
          img.onerror = reject;
          img.src = previewUrl;
        });
        cropPayload = {
          x: croppedArea.x / dims.w,
          y: croppedArea.y / dims.h,
          width: croppedArea.width / dims.w,
          height: croppedArea.height / dims.h,
        };
      }

      await api.upload(project.id, file, {
        rotation,
        page_number: pageNumber,
        crop: cropPayload,
      });

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
          Step 1 — Upload a scanned mathematics textbook page (JPG, PNG, WEBP, or PDF).
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="panel space-y-4 p-5">
          <label className="label">Textbook page</label>
          <label className="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-white/20 bg-ink-800/50 px-4 py-10 hover:border-accent/50">
            <Upload className="text-accent" size={28} />
            <div className="text-center text-sm">
              <div className="font-semibold">Drop a page here or click to browse</div>
              <div className="text-slate-400">JPG · JPEG · PNG · WEBP · PDF · max 25MB</div>
            </div>
            <input
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => onFile(e.target.files?.[0] || null)}
            />
          </label>
          {file && (
            <div className="text-sm text-slate-300">
              Selected: <span className="font-medium text-white">{file.name}</span>
            </div>
          )}

          {isPdf && (
            <div>
              <label className="label">PDF page number</label>
              <input
                type="number"
                min={1}
                className="input"
                value={pageNumber}
                onChange={(e) => setPageNumber(Number(e.target.value) || 1)}
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
            <button className="btn-secondary" disabled={busy || !file} onClick={() => submit(false)}>
              {busy ? <Loader2 className="animate-spin" size={16} /> : null}
              Upload only
            </button>
            <button className="btn-primary" disabled={busy || !file} onClick={() => submit(true)}>
              {busy ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
              Upload & Analyze
            </button>
          </div>
        </div>

        <div className="panel space-y-3 p-5">
          <div className="flex items-center justify-between">
            <label className="label mb-0">Preview · crop · rotate</label>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setRotation((r) => (r + 90) % 360)}
              disabled={!previewUrl}
            >
              <RotateCw size={14} /> Rotate
            </button>
          </div>
          <div className="relative h-[420px] overflow-hidden rounded-xl bg-black/40">
            {previewUrl ? (
              <Cropper
                image={previewUrl}
                crop={crop}
                zoom={zoom}
                rotation={rotation}
                aspect={undefined}
                onCropChange={setCrop}
                onZoomChange={setZoom}
                onCropComplete={onCropComplete}
              />
            ) : (
              <div className="flex h-full items-center justify-center px-6 text-center text-sm text-slate-500">
                {isPdf
                  ? "PDF selected — page will be rasterized on upload. Preview is available after processing."
                  : "Image preview appears here after you select a file."}
              </div>
            )}
          </div>
          {previewUrl && (
            <div>
              <label className="label">Zoom</label>
              <input
                type="range"
                min={1}
                max={3}
                step={0.05}
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
                className="w-full"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
