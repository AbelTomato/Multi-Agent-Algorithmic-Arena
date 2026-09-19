import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { useProblemExplorer } from "./use-problem-explorer";

vi.mock("../lib/api");

const item: api.EvaluationRunItem = {
  evaluation_id: "run-1", problem_id: 1, problem_slug: "two-sum",
  language: "python", run_status: "SUCCEEDED", judge_status: "AC",
  case_version: "v1", case_count: 9, executed_count: 9, passed_count: 9,
  failed_case_index: null, error_category: null, summary: "通过当前版本评测用例",
  created_at: "2026-09-19T04:00:00Z", finished_at: "2026-09-19T04:00:01Z",
  duration_ms: 1000,
};
const page = (items: api.EvaluationRunItem[] = [], total = items.length) => ({
  items, total, limit: 20, offset: 0,
});

beforeEach(() => {
  vi.mocked(api.getProblems).mockResolvedValue([]);
  vi.mocked(api.getProblem).mockImplementation(async (id) => ({
    id, slug: "two-sum", title: "Two Sum", description: "Two Sum",
  }));
  vi.mocked(api.getEvaluationHistory).mockResolvedValue(page());
});

async function selectedExplorer() {
  const hook = renderHook(useProblemExplorer);
  act(() => hook.result.current.selectProblem(1));
  await waitFor(() => expect(hook.result.current.problem?.id).toBe(1));
  await waitFor(() => expect(hook.result.current.evaluationHistoryLoading).toBe(false));
  return hook;
}

describe("evaluation history lifecycle", () => {
  it.each([200, 502, 504, 409])("refreshes the first page after evaluation settles with %s", async (status) => {
    if (status === 200) {
      vi.mocked(api.createEvaluation).mockResolvedValue({
        ...item, status: "AC", run_status: "SUCCEEDED", executed_count: 9,
        passed_count: 9, finished_at: "2026-09-19T04:00:01Z", duration_ms: 1000,
      });
    } else {
      vi.mocked(api.createEvaluation).mockRejectedValue(new Error(`HTTP ${status}`));
    }
    const hook = await selectedExplorer();
    vi.mocked(api.getEvaluationHistory).mockResolvedValue(page([item]));
    act(() => hook.result.current.evaluateProblem());
    await waitFor(() => expect(hook.result.current.evaluationHistory).toEqual([item]));
    expect(api.getEvaluationHistory).toHaveBeenLastCalledWith(expect.objectContaining({ problemId: 1, offset: 0 }));
  });

  it("appends pages and does not request beyond total", async () => {
    vi.mocked(api.getEvaluationHistory).mockResolvedValueOnce(page([item], 2));
    const hook = await selectedExplorer();
    const second = { ...item, evaluation_id: "run-2" };
    vi.mocked(api.getEvaluationHistory).mockResolvedValue(page([second], 2));
    act(() => hook.result.current.loadMoreEvaluationHistory());
    await waitFor(() => expect(hook.result.current.evaluationHistory).toEqual([item, second]));
    expect(api.getEvaluationHistory).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 1 }));
    const calls = vi.mocked(api.getEvaluationHistory).mock.calls.length;
    act(() => hook.result.current.loadMoreEvaluationHistory());
    expect(api.getEvaluationHistory).toHaveBeenCalledTimes(calls);
  });

  it("aborts pending pagination on switching and ignores its late response", async () => {
    vi.mocked(api.getEvaluationHistory).mockResolvedValueOnce(page([item], 2));
    const hook = await selectedExplorer();
    let resolve!: (value: api.EvaluationRunListResponse) => void;
    vi.mocked(api.getEvaluationHistory).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    act(() => hook.result.current.loadMoreEvaluationHistory());
    const signal = vi.mocked(api.getEvaluationHistory).mock.calls.at(-1)?.[0]?.signal;
    act(() => hook.result.current.selectProblem(2));
    expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(hook.result.current.evaluationHistoryLoading).toBe(false));
    await act(async () => resolve(page([item], 2)));
    expect(hook.result.current.evaluationHistory).toEqual([]);
  });

  it("exposes history loading and a controlled error", async () => {
    let reject!: (reason: Error) => void;
    vi.mocked(api.getEvaluationHistory).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    const hook = renderHook(useProblemExplorer);
    act(() => hook.result.current.selectProblem(1));
    expect(hook.result.current.evaluationHistoryLoading).toBe(true);
    await act(async () => reject(new Error("private transport detail")));
    expect(hook.result.current.evaluationHistoryError).toBeTruthy();
    expect(hook.result.current.evaluationHistoryError).not.toContain("private transport detail");
    expect(hook.result.current.evaluationHistoryLoading).toBe(false);
  });
});