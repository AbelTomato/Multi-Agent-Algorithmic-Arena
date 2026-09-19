import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { EvaluationRunItem } from "../lib/api";
import { EvaluationHistory } from "./evaluation-history";

it("renders loading, empty and error states", () => {
  const props = { items: [], total: 0, loading: true, error: null, onLoadMore: vi.fn() };
  const view = render(<EvaluationHistory {...props} />);
  expect(screen.getByText("正在加载评测历史…")).toBeInTheDocument();
  expect(screen.queryByText("当前题目暂无评测记录")).not.toBeInTheDocument();
  view.rerender(<EvaluationHistory {...props} loading={false} />);
  expect(screen.getByText("当前题目暂无评测记录")).toBeInTheDocument();
  view.rerender(<EvaluationHistory {...props} loading={false} error="历史暂不可用" />);
  expect(screen.getByRole("alert")).toHaveTextContent("历史暂不可用");
  expect(screen.queryByText("当前题目暂无评测记录")).not.toBeInTheDocument();
});

it("renders summary labels and hides pagination at total without rendering private fields", () => {
  const succeeded = {
    evaluation_id: "run-1", problem_id: 1, problem_slug: "two-sum", language: "python",
    run_status: "SUCCEEDED", judge_status: "AC", case_version: "v1", case_count: 9,
    executed_count: 9, passed_count: 9, failed_case_index: null, error_category: null,
    summary: "通过当前版本评测用例", created_at: "2026-09-19T04:00:00Z",
    finished_at: "2026-09-19T04:00:01Z", duration_ms: 1000,
    code: "private candidate", stdout: "private output",
  } satisfies EvaluationRunItem & { code: string; stdout: string };
  const failed: EvaluationRunItem = {
    ...succeeded, evaluation_id: "run-2", run_status: "FAILED", judge_status: null,
    executed_count: null, passed_count: null, summary: "评测执行服务暂不可用",
  };
  const onLoadMore = vi.fn();
  const props = { items: [succeeded], total: 2, loading: false, error: null, onLoadMore };
  const view = render(<EvaluationHistory {...props} />);
  expect(screen.getByText("Judge AC")).toBeInTheDocument();
  expect(screen.getByText(/通过 9\/9/)).toHaveTextContent("1000ms");
  fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
  expect(onLoadMore).toHaveBeenCalledOnce();
  view.rerender(<EvaluationHistory {...props} items={[succeeded, failed]} />);
  expect(screen.getByText("FAILED")).toBeInTheDocument();
  expect(screen.getByText(/未产生 Judge 计数/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "加载更多" })).not.toBeInTheDocument();
  expect(screen.queryByText(/private candidate|private output/)).not.toBeInTheDocument();
});