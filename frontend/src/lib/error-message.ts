import { ApiError } from "./api";

type ErrorResource = "problems" | "solution" | "evaluation";

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
    if (error.message === "Evaluation service is busy") {
      return "本地评测正在处理其他请求，请稍后再试";
    }
    if (error.message === "Evaluation controller is unavailable") {
      return "本地评测控制器不可用，未执行候选程序";
    }
    if (error.message === "Evaluation is disabled") {
      return "本地评测功能当前未启用";
    }
    if (error.message === "Evaluation request timed out") {
      return "本次评测超过总期限，已停止等待";
    }
    if (error.status && error.status >= 500) {
      return resource === "solution"
        ? "服务暂时不可用，暂时没生成出解题结果"
        : resource === "evaluation"
          ? "本地评测服务暂时不可用，未执行候选程序"
        : "题目服务暂时不可用，稍后再试";
    }
  }

  return resource === "solution"
    ? "解题请求失败，稍后再试"
    : resource === "evaluation"
      ? "评测请求失败，未执行候选程序"
    : "题目加载失败，稍后再试";
}