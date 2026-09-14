import { ProblemDetailPanel } from "./components/problem-detail-panel";
import { ProblemSidebar } from "./components/problem-sidebar";
import { useProblemExplorer } from "./hooks/use-problem-explorer";

export default function App() {
  const {
    problems,
    problemsLoading,
    problemsError,
    selectedProblemId,
    selectProblem,
    problem,
    problemLoading,
    problemError,
    solution,
    solutionLoading,
    solutionError,
    solveProblem,
  } = useProblemExplorer();

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800/80 bg-slate-950/50">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-5 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-400 font-black text-slate-950">
              A
            </div>
            <div>
              <p className="font-semibold tracking-tight text-white">Algorithmic Arena</p>
              <p className="text-xs text-slate-500">单 Agent 算法题解答演示</p>
            </div>
          </div>
          <span className="hidden rounded-full border border-slate-700 px-3 py-1 text-xs font-medium text-slate-400 sm:inline-flex">
            MVP · 单 Agent
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-8 lg:px-8 lg:py-12">
        <section className="mb-8 max-w-3xl">
          <p className="mb-3 text-sm font-semibold uppercase tracking-[0.22em] text-cyan-300">
            Explore → Solve
          </p>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-5xl">
            先看题目，再生成解法
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-slate-400">
            浏览预置题目，查看完整题面，获取一份 Markdown 解法，代码只展示，不会执行
          </p>
        </section>

        <div className="grid gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <ProblemSidebar
            problems={problems}
            loading={problemsLoading}
            error={problemsError}
            selectedProblemId={selectedProblemId}
            onSelect={selectProblem}
          />

          <ProblemDetailPanel
            problem={problem}
            loading={problemLoading}
            error={problemError}
            solution={solution}
            solutionLoading={solutionLoading}
            solutionError={solutionError}
            onSolve={solveProblem}
          />
        </div>
      </main>
    </div>
  );
}