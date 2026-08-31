"use client";

import { LatexView } from "@/components/LatexView";

/** Render narration with inline $...$ / $$...$$ LaTeX when present. */
export function NarrationView({ text }: { text: string }) {
  if (!text) return null;

  const parts = text.split(/(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g);

  return (
    <span className="leading-relaxed">
      {parts.map((part, i) => {
        if (part.startsWith("$$") && part.endsWith("$$")) {
          return <LatexView key={i} latex={part.slice(2, -2).trim()} block />;
        }
        if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
          return <LatexView key={i} latex={part.slice(1, -1).trim()} />;
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}
