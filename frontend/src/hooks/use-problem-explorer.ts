import { useCallback, useEffect, useRef, useState } from "react";

import {
  createSolution,
  createEvaluation,
  type EvaluationResponse,
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
  const solutionControllerRef = useRef<AbortController | null>(null);
  const solutionRequestIdRef = useRef(0);
  const evaluationControllerRef = useRef<AbortController | null>(null);
  const evaluationRequestIdRef = useRef(0);

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
    return () => {
      solutionControllerRef.current?.abort();
      solutionRequestIdRef.current += 1;
      evaluationControllerRef.current?.abort();
      evaluationRequestIdRef.current += 1;
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
        }
      });
  }, [evaluationLoading, problem]);

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
  };
}