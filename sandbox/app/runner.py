"""执行控制器：Docker 生命周期管理和有界输出采集"""

import shlex
import subprocess
import time
import uuid

from app.protocol import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionExitReason,
    ProtocolVersion,
)

RUNTIME_IMAGE = "python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534"
WALL_TIMEOUT_SECONDS = 5
MAX_OUTPUT_BYTES = 64 * 1024
CPU_LIMIT = "1"
MEMORY_LIMIT = "128m"
MEMORY_SWAP_LIMIT = "128m"
PID_LIMIT = "32"
TMPFS_SIZE = "64m"


class DockerRunner:
    def __init__(self, use_sg_docker: bool = True):
        self.use_sg_docker = use_sg_docker

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if request.protocol_version != ProtocolVersion.JSON_STDIO_V1:
            return ExecutionResult(
                exit_reason=ExecutionExitReason.UNKNOWN_ERROR,
                error_message=f"不支持的协议版本: {request.protocol_version}"
            )

        task_id = request.task_id or f"arena-task-{uuid.uuid4().hex[:12]}"
        container_name = f"{task_id}"
        start_time = time.time()

        try:
            result = self._run_docker_container(
                container_name=container_name,
                code=request.code,
                stdin_input=request.stdin_input,
                timeout=WALL_TIMEOUT_SECONDS
            )
            wall_time_ms = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                exit_reason=result["exit_reason"],
                exit_code=result.get("exit_code"),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                wall_time_ms=wall_time_ms,
                container_id=result.get("container_id"),
                error_message=result.get("error_message")
            )
        except Exception as e:
            wall_time_ms = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                exit_reason=ExecutionExitReason.UNKNOWN_ERROR,
                wall_time_ms=wall_time_ms,
                error_message=f"执行控制器异常: {str(e)}"
            )

    def _run_docker_container(self, container_name: str, code: str,
                             stdin_input: str, timeout: int) -> dict:
        docker_cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            "--network", "none",
            "--read-only",
            "--tmpfs", f"/tmp:size={TMPFS_SIZE},noexec",
            "--user", "nobody",
            "--cpus", CPU_LIMIT,
            "--memory", MEMORY_LIMIT,
            "--memory-swap", MEMORY_SWAP_LIMIT,
            "--pids-limit", PID_LIMIT,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "-i",
            RUNTIME_IMAGE,
            "python3", "-c", code
        ]

        # 修复：使用 sg 时，需要用 -c 参数并正确引用命令
        if self.use_sg_docker:
            # 将 docker 命令转为安全的 shell 字符串
            docker_cmd_str = " ".join(shlex.quote(arg) for arg in docker_cmd)
            docker_cmd = ["sg", "docker", "-c", docker_cmd_str]

        try:
            result = subprocess.run(
                docker_cmd,
                input=stdin_input.encode('utf-8'),
                capture_output=True,
                timeout=timeout,
                check=False
            )

            stdout = result.stdout.decode('utf-8', errors='replace')
            stderr = result.stderr.decode('utf-8', errors='replace')

            total_output = len(stdout.encode('utf-8')) + len(stderr.encode('utf-8'))
            if total_output > MAX_OUTPUT_BYTES:
                return {
                    "exit_reason": ExecutionExitReason.OUTPUT_LIMIT_EXCEEDED,
                    "exit_code": result.returncode,
                    "stdout": self._truncate_output(stdout),
                    "stderr": self._truncate_output(stderr)
                }

            if result.returncode == 0:
                return {
                    "exit_reason": ExecutionExitReason.COMPLETED,
                    "exit_code": 0,
                    "stdout": stdout,
                    "stderr": stderr
                }
            else:
                return {
                    "exit_reason": ExecutionExitReason.NON_ZERO_EXIT,
                    "exit_code": result.returncode,
                    "stdout": stdout,
                    "stderr": stderr
                }

        except subprocess.TimeoutExpired:
            self._cleanup_container(container_name)
            return {
                "exit_reason": ExecutionExitReason.TIMEOUT,
                "error_message": f"超过墙钟限制 {timeout} 秒"
            }
        except Exception as e:
            return {
                "exit_reason": ExecutionExitReason.DOCKER_ERROR,
                "error_message": f"Docker 执行错误: {str(e)}"
            }

    def _truncate_output(self, output: str, max_bytes: int = MAX_OUTPUT_BYTES // 2) -> str:
        encoded = output.encode('utf-8')
        if len(encoded) <= max_bytes:
            return output
        return encoded[:max_bytes].decode('utf-8', errors='ignore') + "\n[... 输出被截断 ...]"

    def _cleanup_container(self, container_name: str):
        try:
            cmd = ["docker", "rm", "-f", container_name]
            if self.use_sg_docker:
                cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
                cmd = ["sg", "docker", "-c", cmd_str]
            subprocess.run(cmd, capture_output=True, timeout=5, check=False)
        except Exception:
            pass
