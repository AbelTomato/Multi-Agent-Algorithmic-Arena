import { useCallback, useEffect, useRef, useState } from "react";

import {
  createSolution,
  createEvaluation,
  type EvaluationResponse,
  getEvaluationHistory,
  type EvaluationRunItem,
  getProblem,
  getProblems,
  type ProblemDetail,
  type ProblemSummary,
  type SolutionResponse,
} from "../lib/api";
import { getErrorMessage } from "../lib/error-message";

export interface ProblemExplorerState {
  problems: ProblemSummary[];
  problemsLoading: boolean;
  problemsError: string | null;
  selectedProblemId: number | null;
  selectProblem: (problemId: number) => void;
  problem: ProblemDetail | null;
  problemLoading: boolean;
  problemError: string | null;
  solution: SolutionResponse | null;
  solutionLoading: boolean;
  solutionError: string | null;
  solveProblem: () => void;
  evaluation: EvaluationResponse | null;
  evaluationLoading: boolean;
  evaluationError: string | null;
  evaluateProblem: () => void;
  evaluationHistory: EvaluationRunItem[];
  evaluationHistoryTotal: number;
  evaluationHistoryLoading: boolean;
  evaluationHistoryError: string | null;
  loadMoreEvaluationHistory: () => void;
}

export function useProblemExplorer(): ProblemExplorerState {
  const [problems, setProblems] = useState<ProblemSummary[]>([]);
  const [problemsLoading, setProblemsLoading] = useState(true);
  const [problemsError, setProblemsError] = useState<string | null>(null);
  const [selectedProblemId, setSelectedProblemId] = useState<number | null>(null);
  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [problemLoading, setProblemLoading] = useState(false);
  const [problemError, setProblemError] = useState<string | null>(null);
  const [solution, setSolution] = useState<SolutionResponse | null>(null);
  const [solutionLoading, setSolutionLoading] = useState(false);
  const [solutionError, setSolutionError] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationResponse | null>(null);
  const [evaluationLoading, setEvaluationLoading] = useState(false);
  const [evaluationError, setEvaluationError] = useState<string | null>(null);
  const [evaluationHistory, setEvaluationHistory] = useState<EvaluationRunItem[]>([]);
  const [evaluationHistoryTotal, setEvaluationHistoryTotal] = useState(0);
  const [evaluationHistoryLoading, setEvaluationHistoryLoading] = useState(false);
  const [evaluationHistoryError, setEvaluationHistoryError] = useState<string | null>(null);
  const [evaluationHistoryRefreshVersion, setEvaluationHistoryRefreshVersion] = useState(0);
  const solutionControllerRef = useRef<AbortController | null>(null);
  const solutionRequestIdRef = useRef(0);
  const evaluationControllerRef = useRef<AbortController | null>(null);
  const evaluationRequestIdRef = useRef(0);
  const evaluationHistoryControllerRef = useRef<AbortController | null>(null);
  const evaluationHistoryRequestIdRef = useRef(0);

  useEffect(() => {
    let active = true;

    async function loadProblems() {
      try {
        const result = await getProblems();
        if (active) {
          setProblems(result);
        }
      } catch (error) {
        if (active) {
          setProblemsError(getErrorMessage(error, "problems"));
        }
      } finally {
        if (active) {
          setProblemsLoading(false);
        }
      }
    }

    void loadProblems();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (selectedProblemId === null) {
      return;
    }

    const problemId = selectedProblemId;
    const controller = new AbortController();

    async function loadProblem() {
      try {
        const result = await getProblem(problemId, controller.signal);
        if (!controller.signal.aborted) {
          setProblem(result);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setProblemError(getErrorMessage(error, "problems"));
        }
      } finally {
        if (!controller.signal.aborted) {
          setProblemLoading(false);
        }
      }
    }

    void loadProblem();
    return () => controller.abort();
  }, [selectedProblemId]);

  useEffect(() => {
    if (selectedProblemId === null) {
      return;
    }

    const controller = new AbortController();
    const requestId = evaluationHistoryRequestIdRef.current + 1;
    evaluationHistoryRequestIdRef.current = requestId;
    evaluationHistoryControllerRef.current?.abort();
    evaluationHistoryControllerRef.current = controller;
    setEvaluationHistory([]);
    setEvaluationHistoryTotal(0);
    setEvaluationHistoryError(null);
    setEvaluationHistoryLoading(true);

    void getEvaluationHistory({
      problemId: selectedProblemId,
      limit: 20,
      offset: 0,
      signal: controller.signal,
    })
      .then((result) => {
        if (requestId === evaluationHistoryRequestIdRef.current && !controller.signal.aborted) {
          setEvaluationHistory(result.items);
          setEvaluationHistoryTotal(result.total);
        }
      })
      .catch((error: unknown) => {
        if (requestId === evaluationHistoryRequestIdRef.current && !controller.signal.aborted) {
          setEvaluationHistoryError(getErrorMessage(error, "evaluation"));
        }
      })
      .finally(() => {
        if (requestId === evaluationHistoryRequestIdRef.current && !controller.signal.aborted) {
          setEvaluationHistoryLoading(false);
          evaluationHistoryControllerRef.current = null;
        }
      });

    return () => {
      controller.abort();
      evaluationHistoryRequestIdRef.current += 1;
    };
  }, [evaluationHistoryRefreshVersion, selectedProblemId]);

  useEffect(() => {
    return () => {
      solutionControllerRef.current?.abort();
      solutionRequestIdRef.current += 1;
      evaluationControllerRef.current?.abort();
      evaluationRequestIdRef.current += 1;
      evaluationHistoryControllerRef.current?.abort();
      evaluationHistoryRequestIdRef.current += 1;
    };
  }, []);

  const selectProblem = useCallback(
    (problemId: number) => {
      if (problemId === selectedProblemId) {
        return;
      }

      solutionControllerRef.current?.abort();
      solutionControllerRef.current = null;
      solutionRequestIdRef.current += 1;
      evaluationControllerRef.current?.abort();
      evaluationControllerRef.current = null;
      evaluationRequestIdRef.current += 1;
      evaluationHistoryControllerRef.current?.abort();
      evaluationHistoryControllerRef.current = null;
      evaluationHistoryRequestIdRef.current += 1;
      setSelectedProblemId(problemId);
      setProblem(null);
      setProblemLoading(true);
      setProblemError(null);
      setSolution(null);
      setSolutionLoading(false);
      setSolutionError(null);
      setEvaluation(null);
      setEvaluationLoading(false);
      setEvaluationError(null);
      setEvaluationHistory([]);
      setEvaluationHistoryTotal(0);
      setEvaluationHistoryLoading(false);
      setEvaluationHistoryError(null);
    },
    [selectedProblemId],
  );

  const solveProblem = useCallback(() => {
    if (!problem || solutionLoading) {
      return;
    }

    solutionControllerRef.current?.abort();
    const controller = new AbortController();
    const requestId = solutionRequestIdRef.current + 1;
    solutionRequestIdRef.current = requestId;
    solutionControllerRef.current = controller;
    setSolution(null);
    setSolutionError(null);
    setSolutionLoading(true);

    const isCurrentRequest = () =>
      requestId === solutionRequestIdRef.current && !controller.signal.aborted;

    void createSolution(problem.id, controller.signal)
      .then((result) => {
        if (isCurrentRequest()) {
          setSolution(result);
        }
      })
      .catch((error: unknown) => {
        if (isCurrentRequest()) {
          setSolutionError(getErrorMessage(error, "solution"));
        }
      })
      .finally(() => {
        if (isCurrentRequest()) {
          setSolutionLoading(false);
          solutionControllerRef.current = null;
        }
      });
  }, [problem, solutionLoading]);

  const evaluateProblem = useCallback(() => {
    if (!problem || evaluationLoading) {
      return;
    }

    evaluationControllerRef.current?.abort();
    const controller = new AbortController();
    const requestId = evaluationRequestIdRef.current + 1;
    evaluationRequestIdRef.current = requestId;
    evaluationControllerRef.current = controller;
    setEvaluation(null);
    setEvaluationError(null);
    setEvaluationLoading(true);

    const isCurrentRequest = () =>
      requestId === evaluationRequestIdRef.current && !controller.signal.aborted;

    void createEvaluation(problem.id, controller.signal)
      .then((result) => {
        if (isCurrentRequest()) {
          setEvaluation(result);
        }
      })
      .catch((error: unknown) => {
        if (isCurrentRequest()) {
          setEvaluationError(getErrorMessage(error, "evaluation"));
        }
      })
      .finally(() => {
        if (isCurrentRequest()) {
          setEvaluationLoading(false);
          evaluationControllerRef.current = null;
          setEvaluationHistoryRefreshVersion((version) => version + 1);
        }
      });
  }, [evaluationLoading, problem]);

  const loadMoreEvaluationHistory = useCallback(() => {
    if (
      selectedProblemId === null ||
      evaluationHistoryLoading ||
      evaluationHistory.length >= evaluationHistoryTotal
    ) {
      return;
    }

    const controller = new AbortController();
    const requestId = evaluationHistoryRequestIdRef.current + 1;
    evaluationHistoryRequestIdRef.current = requestId;
    evaluationHistoryControllerRef.current = controller;
    setEvaluationHistoryLoading(true);
    setEvaluationHistoryError(null);

    void getEvaluationHistory({
      problemId: selectedProblemId,
      limit: 20,
      offset: evaluationHistory.length,
      signal: controller.signal,
    })
      .then((result) => {
        if (requestId === evaluationHistoryRequestIdRef.current && !controller.signal.aborted) {
          setEvaluationHistory((items) => [...items, ...result.items]);
          setEvaluationHistoryTotal(result.total);
        }
      })
      .catch((error: unknown) => {
        if (requestId === evaluationHistoryRequestIdRef.current && !controller.signal.aborted) {
          setEvaluationHistoryError(getErrorMessage(error, "evaluation"));
        }
      })
      .finally(() => {
        if (requestId === evaluationHistoryRequestIdRef.current && !controller.signal.aborted) {
          setEvaluationHistoryLoading(false);
          evaluationHistoryControllerRef.current = null;
        }
      });
  }, [evaluationHistory, evaluationHistoryLoading, evaluationHistoryTotal, selectedProblemId]);

  return {
    problems,
    problemsLoading,
    problemsError,
    selectedProblemId,
    selectProblem,
    problem,
    problemLoading,
    problemError,
    solution,
    solutionLoading,
    solutionError,
    solveProblem,
    evaluation,
    evaluationLoading,
    evaluationError,
    evaluateProblem,
    evaluationHistory,
    evaluationHistoryTotal,
    evaluationHistoryLoading,
    evaluationHistoryError,
    loadMoreEvaluationHistory,
  };
}