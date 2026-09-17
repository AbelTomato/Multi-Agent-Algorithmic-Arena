import type { EvaluationResponse } from "../lib/api";

import { LoadingText } from "./status";
import { Alert } from "./ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

interface EvaluationResultProps {
  evaluation: EvaluationResponse | null;
  loading: boolean;
  error: string | null;
}

const statusClasses = {
  AC: "bg-emerald-400/10 text-emerald-300",
  WA: "bg-amber-400/10 text-amber-300",
  RE: "bg-rose-400/10 text-rose-300",
  TLE: "bg-rose-400/10 text-rose-300",
  MLE: "bg-rose-400/10 text-rose-300",
  OLE: "bg-rose-400/10 text-rose-300",
  UKE: "bg-slate-400/10 text-slate-300",
};

export function EvaluationResult({ evaluation, loading, error }: EvaluationResultProps) {
  return (
    <>
      {error && <Alert>{error}</Alert>}

      {loading && (
        <Card>
          <CardContent className="py-6">
            <LoadingText>正在生成并评测候选程序…</LoadingText>
          </CardContent>
        </Card>
      )}

      {evaluation && !loading && (
        <Card>
          <CardHeader className="border-b border-slate-800/80">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
                  Evaluation
                </p>
                <CardTitle>评测摘要</CardTitle>
              </div>
              <span className={`rounded-full px-3 py-1 text-xs font-medium ${statusClasses[evaluation.status]}`}>
                {evaluation.status}
              </span>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 pt-6 text-sm text-slate-300">
            <p>{evaluation.summary}</p>
            <p className="text-slate-500">
              用例版本 {evaluation.case_version} · 已执行 {evaluation.executed_count}/{evaluation.case_count}
              {" · "}通过 {evaluation.passed_count}
            </p>
            {evaluation.status === "UKE" && (
              <p className="text-slate-500">评测基础设施未能可靠分类本次执行结果。</p>
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}