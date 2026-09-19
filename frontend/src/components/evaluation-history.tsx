import type { EvaluationRunItem } from "../lib/api";

import { LoadingText } from "./status";
import { Alert } from "./ui/alert";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

interface EvaluationHistoryProps {
  items: EvaluationRunItem[];
  total: number;
  loading: boolean;
  error: string | null;
  onLoadMore: () => void;
}

const runStatusClasses: Record<EvaluationRunItem["run_status"], string> = {
  RUNNING: "bg-cyan-400/10 text-cyan-300",
  SUCCEEDED: "bg-emerald-400/10 text-emerald-300",
  FAILED: "bg-rose-400/10 text-rose-300",
  TIMED_OUT: "bg-amber-400/10 text-amber-300",
  REJECTED: "bg-amber-400/10 text-amber-300",
  INTERRUPTED: "bg-slate-400/10 text-slate-300",
};

function formatTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" });
}

export function EvaluationHistory({
  items,
  total,
  loading,
  error,
  onLoadMore,
}: EvaluationHistoryProps) {
  return (
    <Card>
      <CardHeader className="border-b border-slate-800/80">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
              History
            </p>
            <CardTitle>评测历史</CardTitle>
          </div>
          {total > 0 && <span className="text-xs text-slate-500">共 {total} 次</span>}
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-6">
        {error && <Alert>{error}</Alert>}
        {loading && items.length === 0 && <LoadingText>正在加载评测历史…</LoadingText>}
        {!loading && !error && items.length === 0 && (
          <p className="text-sm text-slate-500">当前题目暂无评测记录</p>
        )}
        {items.map((item) => (
          <article key={item.evaluation_id} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${runStatusClasses[item.run_status]}`}>
                  {item.run_status}
                </span>
                {item.judge_status && <span className="text-xs text-slate-400">Judge {item.judge_status}</span>}
              </div>
              <time className="text-xs text-slate-500">{formatTime(item.created_at)}</time>
            </div>
            <p className="mt-3 text-sm text-slate-300">{item.summary}</p>
            <p className="mt-2 text-xs text-slate-500">
              {item.case_version} · {item.passed_count === null ? "未产生 Judge 计数" : `通过 ${item.passed_count}/${item.case_count}`}
              {item.duration_ms === null ? "" : ` · ${item.duration_ms}ms`}
            </p>
          </article>
        ))}
        {items.length < total && (
          <Button type="button" variant="secondary" size="sm" onClick={onLoadMore} disabled={loading}>
            {loading ? "正在加载…" : "加载更多"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}