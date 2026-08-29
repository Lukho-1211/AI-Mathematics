"use client";

import { InlineMath, BlockMath } from "react-katex";

export function LatexView({ latex, block = false }: { latex: string; block?: boolean }) {
  try {
    if (block) return <BlockMath math={latex} />;
    return <InlineMath math={latex} />;
  } catch {
    return (
      <code className="rounded bg-red-500/10 px-1 text-red-200" title="Invalid LaTeX">
        {latex}
      </code>
    );
  }
}
