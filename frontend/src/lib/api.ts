export interface ProblemSummary {
  id: number;
  slug: string;
  title: string;
}

export interface ProblemDetail extends ProblemSummary {
  description: string;
}

export interface SolutionResponse {
  problem_id: number;
  result: string;
  language: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${apiBaseUrl}${path}`, init);
  } catch {
    throw new ApiError("NETWORK_ERROR");
  }

  if (!response.ok) {
    let detail: string | undefined;

    try {
      const payload: unknown = await response.json();
      if (
        typeof payload === "object" &&
        payload !== null &&
        "detail" in payload &&
        typeof payload.detail === "string"
      ) {
        detail = payload.detail;
      }
    } catch {
      // The response may not contain JSON. The status is still useful to callers.
    }

    throw new ApiError(detail ?? `HTTP_${response.status}`, response.status);
  }

  return response.json() as Promise<T>;
}

export function getProblems(): Promise<ProblemSummary[]> {
  return request<ProblemSummary[]>("/api/problems");
}

export function getProblem(problemId: number, signal?: AbortSignal): Promise<ProblemDetail> {
  return request<ProblemDetail>(
    `/api/problems/${problemId}`,
    signal === undefined ? undefined : { signal },
  );
}

export function createSolution(
  problemId: number,
  signal?: AbortSignal,
): Promise<SolutionResponse> {
  const init: RequestInit = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ problem_id: problemId }),
  };

  if (signal !== undefined) {
    init.signal = signal;
  }

  return request<SolutionResponse>("/api/solutions", init);
}