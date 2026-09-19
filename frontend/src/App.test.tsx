import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";

const problems = [
  { id: 1, slug: "two-sum", title: "Two Sum" },
  { id: 2, slug: "valid-parentheses", title: "Valid Parentheses" },
];

const problemDetail = {
  id: 1,
  slug: "two-sum",
  title: "Two Sum",
  description: "# Two Sum\n\nFind two numbers.\n\n- Return their indices.",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockSuccessfulApi(solutionResponse?: unknown) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/api/problems")) {
      return jsonResponse(problems);
    }
    if (url.endsWith("/api/problems/1")) {
      return jsonResponse(problemDetail);
    }
    if (url.endsWith("/api/solutions")) {
      return jsonResponse(
        solutionResponse ?? {
          problem_id: 1,
          result: "## 解题思路\n\n```python\ndef two_sum():\n    pass\n```",
          language: "python",
        },
      );
    }
    if (url.endsWith("/api/evaluations")) {
      return jsonResponse({
        problem_id: 1,
        problem_slug: "two-sum",
        language: "python",
        status: "AC",
        case_version: "v1",
        case_count: 9,
        executed_count: 9,
        passed_count: 9,
        failed_case_index: null,
        summary: "通过当前版本评测用例",
      });
    }
    if (url.includes("/api/evaluations?")) {
      return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 });
    }
    throw new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`);
  });
}

async function selectFirstProblem() {
  render(<App />);
  const problemButton = await screen.findByRole("button", { name: /Two Sum/ });
  fireEvent.click(problemButton);
  await screen.findByRole("heading", { name: "Two Sum", level: 2 });
}

describe("App", () => {
  it("renders the problem list and loads selected problem details", async () => {
    const fetchMock = mockSuccessfulApi();
    render(<App />);

    expect(await screen.findByText("题目列表")).toBeInTheDocument();
    expect(screen.getByText("MVP · 单 Agent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "粤ICP备2026139779号-1" })).toHaveAttribute(
      "href",
      "http://beian.miit.gov.cn",
    );
    expect(await screen.findByRole("button", { name: /Two Sum/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Valid Parentheses/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Two Sum/ }));

    expect(await screen.findByRole("heading", { name: "Two Sum", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Find two numbers.")).toBeInTheDocument();
    const problemDetailCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/problems/1"),
    );
    expect(problemDetailCall?.[1]).toMatchObject({ signal: expect.any(AbortSignal) });
  });

  it("shows a useful empty state when no problems are available", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse([]));
    render(<App />);

    expect(await screen.findByText("暂无可用题目")).toBeInTheDocument();
    expect(screen.getByText("选择一道题目开始")).toBeInTheDocument();
  });

  it("loads and renders only structured evaluation history for the selected problem", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/problems")) return jsonResponse(problems);
      if (url.endsWith("/api/problems/1")) return jsonResponse(problemDetail);
      if (url.includes("/api/evaluations?problem_id=1")) {
        return jsonResponse({
          items: [
            {
              evaluation_id: "11111111-1111-4111-8111-111111111111",
              problem_id: 1,
              problem_slug: "two-sum",
              language: "python",
              run_status: "FAILED",
              judge_status: null,
              case_version: "v1",
              case_count: 9,
              executed_count: null,
              passed_count: null,
              failed_case_index: null,
              summary: "评测执行服务暂不可用",
              error_category: "CONTROLLER_UNAVAILABLE",
              created_at: "2026-09-19T04:30:00Z",
              finished_at: "2026-09-19T04:30:01Z",
              duration_ms: 1000,
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    await selectFirstProblem();

    expect(await screen.findByRole("heading", { name: "评测历史", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText("评测执行服务暂不可用")).toBeInTheDocument();
    expect(screen.queryByText("候选源码")).not.toBeInTheDocument();
    const historyRequest = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/evaluations?problem_id=1"),
    );
    expect(historyRequest?.[1]).toMatchObject({
      credentials: "same-origin",
      signal: expect.any(AbortSignal),
    });
  });

  it("displays detail loading errors", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).endsWith("/api/problems")) {
        return jsonResponse(problems);
      }
      return jsonResponse({ detail: "Problem not found" }, 404);
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Two Sum/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("题目不存在，可能已被移除");
  });

  it("shows solution loading state, renders Markdown and keeps the solve button disabled", async () => {
    const fetchMock = mockSuccessfulApi();
    await selectFirstProblem();

    const solveButton = screen.getByRole("button", { name: "让 Agent 解题" });
    fireEvent.click(solveButton);

    expect(screen.getByRole("button", { name: "正在生成解题结果…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("正在生成解法");
    expect(await screen.findByRole("heading", { name: "解题思路" })).toBeInTheDocument();
    const codeBlock = document.querySelector("pre code");
    expect(codeBlock).toHaveTextContent("def two_sum():");
    expect(codeBlock).toHaveClass("language-python");
    expect(screen.getAllByText("python")).toHaveLength(2);

    const solutionRequest = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/api/solutions"));
    expect(solutionRequest?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ problem_id: 1 }),
    });
  });

  it("shows a controlled error when solution generation fails", async () => {
    await selectFirstProblemWithSolutionFailure();

    fireEvent.click(screen.getByRole("button", { name: "让 Agent 解题" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "暂时没生成出解题结果，稍后再试",
      );
    });
  });

  it("shows a short message when requests are rate limited", async () => {
    await selectFirstProblemWithSolutionRateLimit();

    fireEvent.click(screen.getByRole("button", { name: "让 Agent 解题" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("请求有点频繁，稍后再试");
    });
  });

  it("ignores a solution response after switching to another problem", async () => {
    let resolveSolution: ((response: Response) => void) | undefined;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/problems")) {
        return jsonResponse(problems);
      }
      if (url.endsWith("/api/problems/1")) {
        return jsonResponse(problemDetail);
      }
      if (url.endsWith("/api/problems/2")) {
        return jsonResponse({
          id: 2,
          slug: "valid-parentheses",
          title: "Valid Parentheses",
          description: "# Valid Parentheses\n\nCheck pairs.",
        });
      }
      if (url.endsWith("/api/solutions")) {
        return new Promise<Response>((resolve) => {
          resolveSolution = resolve;
        });
      }
      throw new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`);
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Two Sum/ }));
    await screen.findByRole("heading", { name: "Two Sum", level: 2 });
    fireEvent.click(screen.getByRole("button", { name: "让 Agent 解题" }));

    const solutionRequest = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/solutions"),
    );
    expect(solutionRequest?.[1]).toMatchObject({ signal: expect.any(AbortSignal) });

    fireEvent.click(screen.getByRole("button", { name: /Valid Parentheses/ }));
    expect(
      await screen.findByRole("heading", { name: "Valid Parentheses", level: 2 }),
    ).toBeInTheDocument();
    expect((solutionRequest?.[1] as RequestInit).signal).toHaveProperty("aborted", true);

    resolveSolution?.(
      jsonResponse({
        problem_id: 1,
        result: "## 解题思路\n\n```python\ndef two_sum():\n    pass\n```",
        language: "python",
      }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "解题思路" })).not.toBeInTheDocument();
    });
  });

  it("shows the evaluation summary and aborts an obsolete evaluation after switching problems", async () => {
    let resolveEvaluation: ((response: Response) => void) | undefined;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/problems")) return jsonResponse(problems);
      if (url.endsWith("/api/problems/1")) return jsonResponse(problemDetail);
      if (url.endsWith("/api/problems/2")) {
        return jsonResponse({
          id: 2,
          slug: "valid-parentheses",
          title: "Valid Parentheses",
          description: "# Valid Parentheses",
        });
      }
      if (url.endsWith("/api/evaluations")) {
        return new Promise<Response>((resolve) => {
          resolveEvaluation = resolve;
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Two Sum/ }));
    await screen.findByRole("heading", { name: "Two Sum", level: 2 });
    fireEvent.click(screen.getByRole("button", { name: "评测 Agent 代码" }));

    const evaluationRequest = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/evaluations"),
    );
    expect(evaluationRequest?.[1]).toMatchObject({ signal: expect.any(AbortSignal) });

    fireEvent.click(screen.getByRole("button", { name: /Valid Parentheses/ }));
    await screen.findByRole("heading", { name: "Valid Parentheses", level: 2 });
    expect((evaluationRequest?.[1] as RequestInit).signal).toHaveProperty("aborted", true);

    resolveEvaluation?.(
      jsonResponse({
        problem_id: 1,
        problem_slug: "two-sum",
        language: "python",
        status: "AC",
        case_version: "v1",
        case_count: 9,
        executed_count: 9,
        passed_count: 9,
        failed_case_index: null,
        summary: "通过当前版本评测用例",
      }),
    );

    await waitFor(() => {
      expect(screen.queryByText("通过当前版本评测用例")).not.toBeInTheDocument();
    });
  });
});

async function selectFirstProblemWithSolutionFailure() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/api/problems")) {
      return jsonResponse(problems);
    }
    if (url.endsWith("/api/problems/1")) {
      return jsonResponse(problemDetail);
    }
    return jsonResponse({ detail: "Agent failed to generate a solution" }, 502);
  });
  await selectFirstProblem();
}


async function selectFirstProblemWithSolutionRateLimit() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/api/problems")) {
      return jsonResponse(problems);
    }
    if (url.endsWith("/api/problems/1")) {
      return jsonResponse(problemDetail);
    }
    return jsonResponse({ detail: "Too many requests" }, 429);
  });
  await selectFirstProblem();
}