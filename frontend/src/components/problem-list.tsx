import type { ProblemSummary } from "../lib/api";

interface ProblemListProps {
  problems: ProblemSummary[];
  selectedProblemId: number | null;
  onSelect: (problemId: number) => void;
}

export function ProblemList({
  problems,
  selectedProblemId,
  onSelect,
}: ProblemListProps) {
  return (
    <div className="space-y-2" data-testid="problem-list">
      {problems.map((problem) => (
        <button
          key={problem.id}
          type="button"
          aria-pressed={selectedProblemId === problem.id}
          onClick={() => onSelect(problem.id)}
          className={`w-full rounded-xl border px-4 py-3 text-left transition-colors ${
            selectedProblemId === problem.id
              ? "border-cyan-400/70 bg-cyan-400/10 text-white"
              : "border-transparent bg-slate-950/30 text-slate-300 hover:border-slate-700 hover:bg-slate-800/70 hover:text-white"
          }`}
        >
          <span className="block text-sm font-semibold">{problem.title}</span>
          <span className="mt-1 block text-xs text-slate-500">{problem.slug}</span>
        </button>
      ))}
    </div>
  );
}