import { ApiError } from "./api";

type ErrorResource = "problems" | "solution";

export function getErrorMessage(
  error: unknown,
  resource: ErrorResource,
): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return "请求有点频繁，稍后再试";
    }
    if (error.message === "NETWORK_ERROR") {
      return "连不上后端服务，请确认 API 已启动";
    }
    if (error.message === "Problem not found") {
      return "题目不存在，可能已被移除";
    }
    if (error.message === "Agent failed to generate a solution") {
      return "暂时没生成出解题结果，稍后再试";
    }
    if (error.status && error.status >= 500) {
      return resource === "solution"
        ? "服务暂时不可用，暂时没生成出解题结果"
        : "题目服务暂时不可用，稍后再试";
    }
  }

  return resource === "solution"
    ? "解题请求失败，稍后再试"
    : "题目加载失败，稍后再试";
}