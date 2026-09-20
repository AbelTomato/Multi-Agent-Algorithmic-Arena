package executor

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/runtime"
)

func TestRunnerCompilesCppThenRunsReadOnlyArtifact(t *testing.T) {
	docker := &compileDockerStub{runResults: []dockerRunResult{
		{exitCode: 0}, // root-only artifact directory initialization
		{exitCode: 0}, // non-root compilation
		{exitCode: 0}, // non-root candidate execution
	}}
	runner := NewRunner(docker)
	runner.taskIDGenerator = func() (string, error) { return "arena-task-cpp-unit", nil }

	result := runner.Execute(context.Background(), cppRequest("#include <iostream>\nint main() { std::cout << 42; }"), cppRuntimeConfig())

	if result.ExitReason != protocol.ExitReasonCompleted || result.ExitCode == nil || *result.ExitCode != 0 {
		t.Fatalf("result = %#v, want successful C++ execution", result)
	}
	if !reflect.DeepEqual(docker.createdVolumes, []string{"arena-task-cpp-unit-artifact"}) {
		t.Fatalf("created volumes = %#v", docker.createdVolumes)
	}
	if !reflect.DeepEqual(docker.removedVolumes, []string{"arena-task-cpp-unit-artifact"}) {
		t.Fatalf("removed volumes = %#v", docker.removedVolumes)
	}
	if len(docker.runArgs) != 3 {
		t.Fatalf("run count = %d, want 3", len(docker.runArgs))
	}
	if !containsArgument(docker.runArgs[1], "--user") || !containsArgument(docker.runArgs[1], "65534:65534") {
		t.Fatalf("compile args = %#v, want non-root compiler", docker.runArgs[1])
	}
	if !containsArgument(docker.runArgs[0], "--read-only") || !containsArgument(docker.runArgs[1], "--read-only") {
		t.Fatalf("initialization/compile args must have read-only root filesystems: %#v", docker.runArgs)
	}
	if !containsArgument(docker.runArgs[0], "--cap-add") || !containsArgument(docker.runArgs[0], "CHOWN") {
		t.Fatalf("initialization args = %#v, want the sole CAP_CHOWN grant for artifact ownership setup", docker.runArgs[0])
	}
	for _, args := range docker.runArgs[1:] {
		if containsArgument(args, "--cap-add") {
			t.Fatalf("compile/run args = %#v, must not gain Linux capabilities", args)
		}
	}
	if !containsArgument(docker.runArgs[2], "type=volume,src=arena-task-cpp-unit-artifact,dst=/arena/out,readonly") || !containsArgument(docker.runArgs[2], "/arena/out/program") {
		t.Fatalf("run args = %#v, want read-only artifact and fixed program", docker.runArgs[2])
	}
}

func TestRunnerReturnsCompilationFailureWithoutExecutingCandidate(t *testing.T) {
	docker := &compileDockerStub{runResults: []dockerRunResult{
		{exitCode: 0},
		{exitCode: 1},
	}}
	runner := NewRunner(docker)
	runner.taskIDGenerator = func() (string, error) { return "arena-task-cpp-compile-error", nil }

	result := runner.Execute(context.Background(), cppRequest("not valid cpp"), cppRuntimeConfig())

	if result.ExitReason != protocol.ExitReasonCompilationFailed || result.ExitCode == nil || *result.ExitCode != 1 {
		t.Fatalf("result = %#v, want compilation failure", result)
	}
	if len(docker.runArgs) != 2 {
		t.Fatalf("run count = %d, want initialization and compilation only", len(docker.runArgs))
	}
	if !reflect.DeepEqual(docker.removedVolumes, []string{"arena-task-cpp-compile-error-artifact"}) {
		t.Fatalf("removed volumes = %#v", docker.removedVolumes)
	}
}

func TestRunnerRejectsMissingCompiledProgramWithoutExecutingCandidate(t *testing.T) {
	docker := &compileDockerStub{runResults: []dockerRunResult{
		{exitCode: 0},
		{exitCode: 1},
	}}
	runner := NewRunner(docker)
	runner.taskIDGenerator = func() (string, error) { return "arena-task-cpp-missing-program", nil }

	result := runner.Execute(context.Background(), cppRequest("int main() {}"), cppRuntimeConfig())

	if result.ExitReason != protocol.ExitReasonCompilationFailed {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCompilationFailed)
	}
	if len(docker.runArgs) != 2 {
		t.Fatalf("run count = %d, want initialization and compile/artifact-check only", len(docker.runArgs))
	}
	if !containsArgument(docker.runArgs[1], "cat > /arena/out/main.cpp && \"$@\" && test -x /arena/out/program") {
		t.Fatalf("compile args = %#v, want fixed executable artifact check", docker.runArgs[1])
	}
}

func TestRunnerCleansArtifactWhenCompilationInfrastructureFails(t *testing.T) {
	compileFailure := errors.New("docker unavailable")
	docker := &compileDockerStub{runResults: []dockerRunResult{
		{exitCode: 0},
		{err: compileFailure},
	}}
	runner := NewRunner(docker)
	runner.taskIDGenerator = func() (string, error) { return "arena-task-cpp-docker-error", nil }

	result := runner.Execute(context.Background(), cppRequest("int main() {}"), cppRuntimeConfig())

	if result.ExitReason != protocol.ExitReasonDockerError {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonDockerError)
	}
	if !reflect.DeepEqual(docker.removedVolumes, []string{"arena-task-cpp-docker-error-artifact"}) {
		t.Fatalf("removed volumes = %#v", docker.removedVolumes)
	}
}

func TestRunnerReturnsCompilationTimeoutWithoutExecutingCandidate(t *testing.T) {
	docker := &compileDockerStub{runResults: []dockerRunResult{
		{exitCode: 0},
		{waitForContext: true},
	}}
	runner := NewRunner(docker)
	runner.taskIDGenerator = func() (string, error) { return "arena-task-cpp-compile-timeout", nil }
	config := cppRuntimeConfig()
	config.CompileWallTimeout = time.Millisecond

	result := runner.Execute(context.Background(), cppRequest("int main() {}"), config)

	if result.ExitReason != protocol.ExitReasonCompilationTimeout {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCompilationTimeout)
	}
	if len(docker.runArgs) != 2 {
		t.Fatalf("run count = %d, want initialization and compilation only", len(docker.runArgs))
	}
	if !reflect.DeepEqual(docker.removedVolumes, []string{"arena-task-cpp-compile-timeout-artifact"}) {
		t.Fatalf("removed volumes = %#v", docker.removedVolumes)
	}
}

func TestRunnerReturnsCompilationOutputLimitWithoutExecutingCandidate(t *testing.T) {
	docker := &compileDockerStub{runResults: []dockerRunResult{
		{exitCode: 0},
		{stdout: make([]byte, 64*1024+1)},
	}}
	runner := NewRunner(docker)
	runner.taskIDGenerator = func() (string, error) { return "arena-task-cpp-compile-output-limit", nil }

	result := runner.Execute(context.Background(), cppRequest("int main() {}"), cppRuntimeConfig())

	if result.ExitReason != protocol.ExitReasonCompilationOLE {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCompilationOLE)
	}
	if len(docker.runArgs) != 2 {
		t.Fatalf("run count = %d, want initialization and compilation only", len(docker.runArgs))
	}
	if !reflect.DeepEqual(docker.removedVolumes, []string{"arena-task-cpp-compile-output-limit-artifact"}) {
		t.Fatalf("removed volumes = %#v", docker.removedVolumes)
	}
}

type dockerRunResult struct {
	exitCode       int
	inspect        InspectResult
	err            error
	waitForContext bool
	stdout         []byte
}

type compileDockerStub struct {
	runResults     []dockerRunResult
	runArgs        [][]string
	createdVolumes []string
	removedVolumes []string
}

func (stub *compileDockerStub) Run(ctx context.Context, args []string, _ []byte, collector *OutputCollector) (int, InspectResult, error) {
	stub.runArgs = append(stub.runArgs, append([]string(nil), args...))
	result := stub.runResults[len(stub.runArgs)-1]
	if result.waitForContext {
		<-ctx.Done()
		return 0, InspectResult{}, ctx.Err()
	}
	if len(result.stdout) > 0 {
		collector.WriteStdout(result.stdout)
	}
	return result.exitCode, result.inspect, result.err
}

func (stub *compileDockerStub) CreateArtifactVolume(_ context.Context, volumeID, taskID string) error {
	stub.createdVolumes = append(stub.createdVolumes, volumeID)
	if taskID == "" {
		return errors.New("missing task ID")
	}
	return nil
}

func (stub *compileDockerStub) RemoveArtifactVolume(_ context.Context, volumeID, taskID string) error {
	stub.removedVolumes = append(stub.removedVolumes, volumeID)
	if taskID == "" {
		return errors.New("missing task ID")
	}
	return nil
}

func cppRequest(source string) protocol.ExecuteRequest {
	return protocol.ExecuteRequest{
		APIVersion: protocol.ExecutionAPIV2,
		RuntimeID:  "cpp-gcc-14-cpp20-v1",
		Source:     source,
		StdinInput: "{}",
		IOProtocol: protocol.JSONStdioV1,
	}
}

func cppRuntimeConfig() runtime.Config {
	return runtime.Config{
		ID:                 "cpp-gcc-14-cpp20-v1",
		Image:              "example.invalid/gcc@sha256:fixed",
		IOProtocols:        map[string]struct{}{protocol.JSONStdioV1: {}},
		WallTimeout:        5 * time.Second,
		CompileWallTimeout: 15 * time.Second,
		NetworkMode:        "none",
		ReadOnly:           true,
		Tmpfs:              "/tmp:size=64m,noexec",
		CompileTmpfs:       "/tmp:size=64m,exec",
		User:               "65534:65534",
		CPUs:               "1",
		Memory:             "128m",
		MemorySwap:         "128m",
		CompileMemory:      "512m",
		CompileMemorySwap:  "512m",
		PIDsLimit:          "32",
		CapDrop:            "ALL",
		NoNewPrivileges:    true,
		MaxOutputBytes:     64 * 1024,
		CompileCommand: []string{
			"g++", "-std=c++20", "-O2", "-pipe", "-o", "/arena/out/program", "/arena/out/main.cpp",
		},
		CompiledProgram: "/arena/out/program",
	}
}
