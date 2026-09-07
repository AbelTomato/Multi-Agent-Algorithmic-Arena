import { useEffect, useState } from "react";

import { Alert } from "./components/ui/alert";
import { Button } from "./components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./components/ui/card";
import { MarkdownContent } from "./components/markdown-content";
import {
  ApiError,
  createSolution,
  getProblem,
  getProblems,
  type ProblemDetail,
  type ProblemSummary,
  type SolutionResponse,
} from "./lib/api";

function getErrorMessage(error: unknown, resource: "problems" | "solution"): string {
  if (error instanceof ApiError) {
    if (error.message === "NETWORK_ERROR") {
      return "无法连接后端服务，请检查 API 服务是否已启动。";
    }
    if (error.message === "Problem not found") {
      return "题目不存在，可能已经被移除。";
    }
    if (error.message === "Agent failed to generate a solution") {
      return "Agent 暂时无法生成解题结果，请稍后重试。";
    }
    if (error.status && error.status >= 500) {
      return resource === "solution"
        ? "服务暂时不可用，Agent 未能生成解题结果。"
        : "题目服务暂时不可用，请稍后重试。";
    }
  }

  return resource === "solution"
    ? "解题请求失败，请稍后重试。"
    : "题目加载失败，请稍后重试。";
}

function LoadingText({ children }: { children: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-slate-400" role="status">
      <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-300" />
      {children}
    </div>
  );
}

function EmptyState({ children }: { children: string }) {
  return <p className="rounded-xl border border-dashed border-slate-700 p-5 text-sm text-slate-500">{children}</p>;
}

function ProblemList({
  problems,
  selectedProblemId,
  onSelect,
}: {
  problems: ProblemSummary[];
  selectedProblemId: number | null;
  onSelect: (problemId: number) => void;
}) {
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

function ProblemDetailPanel({
  problem,
  loading,
  error,
  solution,
  solutionLoading,
  solutionError,
  onSolve,
}: {
  problem: ProblemDetail | null;
  loading: boolean;
  error: string | null;
  solution: SolutionResponse | null;
  solutionLoading: boolean;
  solutionError: string | null;
  onSolve: () => void;
}) {
  if (loading) {
    return (
      <Card className="min-h-96">
        <CardContent className="flex min-h-96 items-center justify-center">
          <LoadingText>正在加载题目详情…</LoadingText>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="min-h-96">
        <CardContent className="flex min-h-96 items-center">
          <Alert className="w-full">{error}</Alert>
        </CardContent>
      </Card>
    );
  }

  if (!problem) {
    return (
      <Card className="min-h-96">
        <CardContent className="flex min-h-96 flex-col items-center justify-center text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-cyan-400/10 text-2xl text-cyan-300">
            →
          </div>
          <h2 className="text-lg font-semibold text-white">选择一道题目开始</h2>
          <p className="mt-2 max-w-sm text-sm leading-6 text-slate-500">
            从左侧列表选择题目，页面会按需加载完整题面。
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="border-b border-slate-800/80">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Problem</p>
              <CardTitle className="text-2xl">{problem.title}</CardTitle>
              <CardDescription className="mt-2">/{problem.slug}</CardDescription>
            </div>
            <Button type="button" onClick={onSolve} disabled={solutionLoading}>
              {solutionLoading ? "正在生成解题结果…" : "让 Agent 解题"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          <MarkdownContent content={problem.description} />
        </CardContent>
      </Card>

      {solutionError && <Alert>{solutionError}</Alert>}

      {solutionLoading && (
        <Card>
          <CardContent className="py-6">
            <LoadingText>Agent 正在分析题目，请稍候…</LoadingText>
          </CardContent>
        </Card>
      )}

      {solution && !solutionLoading && (
        <Card>
          <CardHeader className="border-b border-slate-800/80">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300">Solution</p>
                <CardTitle>Agent 解题结果</CardTitle>
              </div>
              <span className="rounded-full bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
                {solution.language}
              </span>
            </div>
          </CardHeader>
          <CardContent className="pt-6">
            <MarkdownContent content={solution.result} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function App() {
  const [problems, setProblems] = useState<ProblemSummary[]>([]);
  const [problemsLoading, setProblemsLoading] = useState(true);
  const [problemsError, setProblemsError] = useState<string | null>(null);
  const [selectedProblemId, setSelectedProblemId] = useState<number | null>(null);
  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [problemLoading, setProblemLoading] = useState(false);
  const [problemError, setProblemError] = useState<string | null>(null);
  const [solution, setSolution] = useState<SolutionResponse | null>(null);
  const [solutionLoading, setSolutionLoading] = useState(false);
  const [solutionError, setSolutionError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadProblems() {
      try {
        const result = await getProblems();
        if (active) {
          setProblems(result);
        }
      } catch (error) {
        if (active) {
          setProblemsError(getErrorMessage(error, "problems"));
        }
      } finally {
        if (active) {
          setProblemsLoading(false);
        }
      }
    }

    void loadProblems();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (selectedProblemId === null) {
      return;
    }

    const problemId = selectedProblemId;
    const controller = new AbortController();
    setProblemLoading(true);
    setProblemError(null);
    setProblem(null);
    setSolution(null);
    setSolutionError(null);

    async function loadProblem() {
      try {
        const result = await getProblem(problemId, controller.signal);
        if (!controller.signal.aborted) {
          setProblem(result);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setProblemError(getErrorMessage(error, "problems"));
        }
      } finally {
        if (!controller.signal.aborted) {
          setProblemLoading(false);
        }
      }
    }

    void loadProblem();
    return () => controller.abort();
  }, [selectedProblemId]);

  async function handleSolve() {
    if (!problem || solutionLoading) {
      return;
    }

    setSolution(null);
    setSolutionError(null);
    setSolutionLoading(true);

    try {
      const result = await createSolution(problem.id);
      setSolution(result);
    } catch (error) {
      setSolutionError(getErrorMessage(error, "solution"));
    } finally {
      setSolutionLoading(false);
    }
  }

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
            MVP · MockAgent
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-8 lg:px-8 lg:py-12">
        <section className="mb-8 max-w-3xl">
          <p className="mb-3 text-sm font-semibold uppercase tracking-[0.22em] text-cyan-300">Explore → Solve</p>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-5xl">
            让 Agent 解释每一道算法题。
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-slate-400">
            浏览预置题目，查看完整题面，并获取一次性返回的 Markdown 解题方案。代码仅展示，不会在服务端或浏览器执行。
          </p>
        </section>

        <div className="grid gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <Card className="h-fit lg:sticky lg:top-5">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle>题目列表</CardTitle>
                {!problemsLoading && !problemsError && (
                  <span className="rounded-full bg-slate-800 px-2.5 py-1 text-xs text-slate-400">
                    {problems.length}
                  </span>
                )}
              </div>
              <CardDescription>选择题目查看详情</CardDescription>
            </CardHeader>
            <CardContent>
              {problemsLoading && <LoadingText>正在加载题目…</LoadingText>}
              {problemsError && <Alert>{problemsError}</Alert>}
              {!problemsLoading && !problemsError && problems.length === 0 && (
                <EmptyState>暂无可用题目。</EmptyState>
              )}
              {!problemsLoading && !problemsError && problems.length > 0 && (
                <ProblemList
                  problems={problems}
                  selectedProblemId={selectedProblemId}
                  onSelect={setSelectedProblemId}
                />
              )}
            </CardContent>
          </Card>

          <ProblemDetailPanel
            problem={problem}
            loading={problemLoading}
            error={problemError}
            solution={solution}
            solutionLoading={solutionLoading}
            solutionError={solutionError}
            onSolve={() => void handleSolve()}
          />
        </div>
      </main>
    </div>
  );
}