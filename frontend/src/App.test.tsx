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

    expect(await screen.findByText("暂无可用题目。")).toBeInTheDocument();
    expect(screen.getByText("选择一道题目开始")).toBeInTheDocument();
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

    expect(await screen.findByRole("alert")).toHaveTextContent("题目不存在，可能已经被移除。");
  });

  it("shows solution loading state, renders Markdown and keeps the solve button disabled", async () => {
    const fetchMock = mockSuccessfulApi();
    await selectFirstProblem();

    const solveButton = screen.getByRole("button", { name: "让 Agent 解题" });
    fireEvent.click(solveButton);

    expect(screen.getByRole("button", { name: "正在生成解题结果…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Agent 正在分析题目");
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
        "Agent 暂时无法生成解题结果，请稍后重试。",
      );
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