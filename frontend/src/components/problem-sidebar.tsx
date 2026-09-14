import type { ProblemSummary } from "../lib/api";

import { ProblemList } from "./problem-list";
import { EmptyState, LoadingText } from "./status";
import { Alert } from "./ui/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";

interface ProblemSidebarProps {
  problems: ProblemSummary[];
  loading: boolean;
  error: string | null;
  selectedProblemId: number | null;
  onSelect: (problemId: number) => void;
}

export function ProblemSidebar({
  problems,
  loading,
  error,
  selectedProblemId,
  onSelect,
}: ProblemSidebarProps) {
  return (
    <Card className="h-fit lg:sticky lg:top-5">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>题目列表</CardTitle>
          {!loading && !error && (
            <span className="rounded-full bg-slate-800 px-2.5 py-1 text-xs text-slate-400">
              {problems.length}
            </span>
          )}
        </div>
        <CardDescription>选一道题查看详情</CardDescription>
      </CardHeader>
      <CardContent>
        {loading && <LoadingText>正在加载题目…</LoadingText>}
        {error && <Alert>{error}</Alert>}
        {!loading && !error && problems.length === 0 && (
          <EmptyState>暂无可用题目</EmptyState>
        )}
        {!loading && !error && problems.length > 0 && (
          <ProblemList
            problems={problems}
            selectedProblemId={selectedProblemId}
            onSelect={onSelect}
          />
        )}
      </CardContent>
    </Card>
  );
}