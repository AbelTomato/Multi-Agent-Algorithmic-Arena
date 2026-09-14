import type { SolutionResponse } from "../lib/api";

import { MarkdownContent } from "./markdown-content";
import { LoadingText } from "./status";
import { Alert } from "./ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

interface SolutionResultProps {
  solution: SolutionResponse | null;
  loading: boolean;
  error: string | null;
}

export function SolutionResult({
  solution,
  loading,
  error,
}: SolutionResultProps) {
  return (
    <>
      {error && <Alert>{error}</Alert>}

      {loading && (
        <Card>
          <CardContent className="py-6">
            <LoadingText>正在生成解法…</LoadingText>
          </CardContent>
        </Card>
      )}

      {solution && !loading && (
        <Card>
          <CardHeader className="border-b border-slate-800/80">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300">
                  Solution
                </p>
                <CardTitle>解题结果</CardTitle>
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
    </>
  );
}