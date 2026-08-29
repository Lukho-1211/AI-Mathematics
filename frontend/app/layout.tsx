import type { Metadata } from "next";
import { IBM_Plex_Sans, Fraunces } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import "katex/dist/katex.min.css";

const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-geist-sans",
});

const display = Fraunces({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "MathViz — Textbook → Explanation Video",
  description:
    "Upload a scanned mathematics textbook page and generate a MathVizAI explanation video.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${sans.variable} ${display.variable} font-sans`}>
        <header className="sticky top-0 z-40 border-b border-white/10 bg-ink-950/80 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
            <Link href="/" className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-ink-950 font-bold">
                Σ
              </div>
              <div>
                <div className="font-display text-lg leading-tight">MathViz</div>
                <div className="text-[11px] text-slate-400">Textbook → Explanation Video</div>
              </div>
            </Link>
            <nav className="flex items-center gap-2">
              <Link href="/" className="btn-secondary">
                Dashboard
              </Link>
              <Link href="/create" className="btn-primary">
                New Video
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
