import type { ReactNode } from "react";

export function LoadingText({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 text-sm text-slate-400" role="status">
      <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-300" />
      {children}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-xl border border-dashed border-slate-700 p-5 text-sm text-slate-500">
      {children}
    </p>
  );
}