import type {
  EvaluationResponse,
  EvaluationRunItem,
  ProblemDetail,
  SolutionResponse,
} from "../lib/api";

import { EvaluationHistory } from "./evaluation-history";
import { MarkdownContent } from "./markdown-content";
import { SolutionResult } from "./solution-result";
import { EvaluationResult } from "./evaluation-result";
import { LoadingText } from "./status";
import { Alert } from "./ui/alert";
import { Button } from "./ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";

interface ProblemDetailPanelProps {
  problem: ProblemDetail | null;
  loading: boolean;
  error: string | null;
  solution: SolutionResponse | null;
  solutionLoading: boolean;
  solutionError: string | null;
  onSolve: () => void;
  evaluation: EvaluationResponse | null;
  evaluationLoading: boolean;
  evaluationError: string | null;
  onEvaluate: () => void;
  evaluationHistory: EvaluationRunItem[];
  evaluationHistoryTotal: number;
  evaluationHistoryLoading: boolean;
  evaluationHistoryError: string | null;
  onLoadMoreEvaluationHistory: () => void;
}

export function ProblemDetailPanel({
  problem,
  loading,
  error,
  solution,
  solutionLoading,
  solutionError,
  onSolve,
  evaluation,
  evaluationLoading,
  evaluationError,
  onEvaluate,
  evaluationHistory,
  evaluationHistoryTotal,
  evaluationHistoryLoading,
  evaluationHistoryError,
  onLoadMoreEvaluationHistory,
}: ProblemDetailPanelProps) {
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
            从左侧列表选一道题，查看完整题面
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
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
                Problem
              </p>
              <CardTitle className="text-2xl">{problem.title}</CardTitle>
              <CardDescription className="mt-2">/{problem.slug}</CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={onSolve} disabled={solutionLoading}>
                {solutionLoading ? "正在生成解题结果…" : "让 Agent 解题"}
              </Button>
              <Button type="button" onClick={onEvaluate} disabled={evaluationLoading}>
                {evaluationLoading ? "正在评测…" : "评测 Agent 代码"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          <MarkdownContent content={problem.description} />
        </CardContent>
      </Card>

      <SolutionResult
        solution={solution}
        loading={solutionLoading}
        error={solutionError}
      />
      <EvaluationResult
        evaluation={evaluation}
        loading={evaluationLoading}
        error={evaluationError}
      />
      <EvaluationHistory
        items={evaluationHistory}
        total={evaluationHistoryTotal}
        loading={evaluationHistoryLoading}
        error={evaluationHistoryError}
        onLoadMore={onLoadMoreEvaluationHistory}
      />
    </div>
  );
}