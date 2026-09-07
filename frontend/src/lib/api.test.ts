import { describe, expect, it, vi } from "vitest";

import { ApiError, createSolution, getProblem, getProblems } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  it("loads problems and problem details from the API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/problems/1")) {
        return jsonResponse({ id: 1, slug: "two-sum", title: "Two Sum", description: "# Two Sum" });
      }
      return jsonResponse([{ id: 1, slug: "two-sum", title: "Two Sum" }]);
    });

    await expect(getProblems()).resolves.toEqual([
      { id: 1, slug: "two-sum", title: "Two Sum" },
    ]);
    await expect(getProblem(1)).resolves.toEqual({
      id: 1,
      slug: "two-sum",
      title: "Two Sum",
      description: "# Two Sum",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("sends only the problem id when creating a solution", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        jsonResponse({ problem_id: 7, result: "## 解题思路", language: "python" }),
      );

    await expect(createSolution(7)).resolves.toEqual({
      problem_id: 7,
      result: "## 解题思路",
      language: "python",
    });

    const [, request] = fetchMock.mock.calls[0];
    expect(request).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem_id: 7 }),
    });
    expect(String(request?.body)).not.toContain("prompt");
    expect(String(request?.body)).not.toContain("model");
    expect(String(request?.body)).not.toContain("provider");
  });

  it("converts network and HTTP failures to ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("offline"));
    await expect(getProblems()).rejects.toMatchObject({
      name: "ApiError",
      message: "NETWORK_ERROR",
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ detail: "Problem not found" }, 404),
    );
    await expect(getProblem(999)).rejects.toEqual(
      expect.objectContaining<ApiError>({
        name: "ApiError",
        message: "Problem not found",
        status: 404,
      }),
    );
  });
});