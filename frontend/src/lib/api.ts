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

export type EvaluationStatus = "AC" | "WA" | "RE" | "TLE" | "MLE" | "OLE" | "UKE";

export interface EvaluationResponse {
  problem_id: number;
  problem_slug: string;
  language: "python";
  status: EvaluationStatus;
  case_version: string;
  case_count: number;
  executed_count: number;
  passed_count: number;
  failed_case_index: number | null;
  summary: string;
  evaluation_id: string;
  run_status: EvaluationRunStatus;
  created_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export type EvaluationRunStatus =
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "TIMED_OUT"
  | "REJECTED"
  | "INTERRUPTED";

export type EvaluationErrorCategory =
  | "AGENT_ERROR"
  | "CONTROLLER_BUSY"
  | "CONTROLLER_UNAVAILABLE"
  | "CONTROLLER_TIMEOUT"
  | "CONTROLLER_RESPONSE_ERROR"
  | "EVALUATION_TIMEOUT"
  | "INTERNAL_ERROR";

export interface EvaluationRunItem {
  evaluation_id: string;
  problem_id: number;
  problem_slug: string;
  language: "python";
  run_status: EvaluationRunStatus;
  judge_status: EvaluationStatus | null;
  case_version: string;
  case_count: number;
  executed_count: number | null;
  passed_count: number | null;
  failed_case_index: number | null;
  summary: string;
  error_category: EvaluationErrorCategory | null;
  created_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface EvaluationRunListResponse {
  items: EvaluationRunItem[];
  total: number;
  limit: number;
  offset: number;
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

export function createEvaluation(
  problemId: number,
  signal?: AbortSignal,
): Promise<EvaluationResponse> {
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

  return request<EvaluationResponse>("/api/evaluations", init);
}

export function getEvaluationHistory({
  problemId,
  limit = 20,
  offset = 0,
  signal,
}: {
  problemId?: number;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
} = {}): Promise<EvaluationRunListResponse> {
  const params = new URLSearchParams();
  if (problemId !== undefined) params.set("problem_id", String(problemId));
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return request<EvaluationRunListResponse>(`/api/evaluations?${params.toString()}`, {
    credentials: "same-origin",
    ...(signal === undefined ? {} : { signal }),
  });
}

export function getEvaluationRun(
  evaluationId: string,
  signal?: AbortSignal,
): Promise<EvaluationRunItem> {
  return request<EvaluationRunItem>(`/api/evaluations/${encodeURIComponent(evaluationId)}`, {
    credentials: "same-origin",
    ...(signal === undefined ? {} : { signal }),
  });
}