package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/executor"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/httpapi"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
	runtimeconfig "github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/runtime"
)

const timeoutResponseDeadline = 6 * time.Second

func TestMain(m *testing.M) {
	if os.Getenv("ARENA_SANDBOX_INTEGRATION") != "1" {
		os.Exit(0)
	}
	if _, err := exec.LookPath("docker"); err != nil {
		os.Exit(0)
	}
	code := m.Run()
	if err := assertNoArenaContainers(); err != nil {
		code = 1
	}
	os.Exit(code)
}

func TestRunnerRealDockerLifecycle(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	cases := []struct {
		name       string
		code       string
		wantReason protocol.ExitReason
	}{
		{name: "completed", code: `print("ok")`, wantReason: protocol.ExitReasonCompleted},
		{name: "non_zero_exit", code: `raise RuntimeError("expected")`, wantReason: protocol.ExitReasonNonZeroExit},
		{name: "timeout", code: `import time; time.sleep(10)`, wantReason: protocol.ExitReasonTimeout},
		{name: "output_limit", code: `import sys; sys.stdout.write("x" * (70 * 1024))`, wantReason: protocol.ExitReasonOutputLimitExceeded},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			result := runner.Execute(context.Background(), request(testCase.code), pythonRuntime(t))
			if result.ExitReason != testCase.wantReason {
				t.Fatalf("exit reason = %q, want %q", result.ExitReason, testCase.wantReason)
			}
			if result.WallTimeMS < 0 {
				t.Fatalf("wall time = %d, want non-negative", result.WallTimeMS)
			}
			assertNoArenaContainersForTest(t)
		})
	}
}

func TestRunnerRealDockerCppCompilationLifecycle(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	config, err := runtimeconfig.NewRegistry().Resolve(runtimeconfig.CppGcc14Cpp20V1)
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name       string
		code       string
		wantReason protocol.ExitReason
		wantStdout string
	}{
		{
			name:       "cpp20_program",
			code:       "#include <iostream>\nint main() { std::cout << 42; }",
			wantReason: protocol.ExitReasonCompleted,
			wantStdout: "42",
		},
		{
			name:       "compile_error",
			code:       "int main( {",
			wantReason: protocol.ExitReasonCompilationFailed,
		},
		{
			name:       "runtime_timeout",
			code:       "int main() { for (;;) {} }",
			wantReason: protocol.ExitReasonTimeout,
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			result := runner.Execute(context.Background(), protocol.ExecuteRequest{
				APIVersion: protocol.ExecutionAPIV2,
				RuntimeID:  runtimeconfig.CppGcc14Cpp20V1,
				Source:     testCase.code,
				StdinInput: "{}",
				IOProtocol: protocol.JSONStdioV1,
			}, config)
			if result.ExitReason != testCase.wantReason {
				t.Fatalf("exit reason = %q, want %q; stderr=%q", result.ExitReason, testCase.wantReason, result.Stderr)
			}
			if result.Stdout != testCase.wantStdout {
				t.Fatalf("stdout = %q, want %q", result.Stdout, testCase.wantStdout)
			}
			assertNoArenaContainersForTest(t)
			assertNoArenaArtifactVolumesForTest(t)
		})
	}
}

func TestRecoverStaleTasksRemovesVerifiedRealDockerTask(t *testing.T) {
	taskID := fmt.Sprintf("arena-task-recovery-%d", time.Now().UnixNano())
	createArgs := executor.NewRunner(nil).BuildDockerRunArgs(taskID, pythonRuntime(t), `import time; time.sleep(60)`)
	createArgs = append([]string{"run", "--detach"}, createArgs[1:]...)
	if output, err := exec.Command("docker", createArgs...).CombinedOutput(); err != nil {
		t.Fatalf("create stale Arena task: %v", sanitizeDockerTestError(err, output))
	}
	t.Cleanup(func() { removeVerifiedArenaTaskForTest(t, taskID) })

	if err := executor.RecoverStaleTasks(context.Background(), executor.NewDockerCLI()); err != nil {
		t.Fatalf("RecoverStaleTasks() error = %v", err)
	}
	if output, err := exec.Command("docker", "inspect", taskID).CombinedOutput(); err == nil {
		t.Fatalf("recovered task %q still exists", taskID)
	} else if !strings.Contains(strings.ToLower(string(output)), "no such") {
		t.Fatalf("inspect recovered task: %v", sanitizeDockerTestError(err, output))
	}
	assertNoArenaContainersForTest(t)
}

func TestControllerProcessRestartRecoversActiveTask(t *testing.T) {
	assertNoArenaContainersForTest(t)
	ensureControllerPortAvailable(t)

	controllerBinary := buildControllerBinaryForTest(t)
	first := startControllerProcessForTest(t, controllerBinary)
	defer stopControllerProcessForTest(t, first)

	requestDone := make(chan error, 1)
	go func() {
		response, err := http.Post("http://127.0.0.1:8001/execute", "application/json", strings.NewReader(`{"api_version":"execution-api-v2","runtime_id":"python-3.11-v1","source":"import time; time.sleep(30)","stdin_input":"{}","io_protocol":"json-stdio-v1"}`))
		if response != nil {
			response.Body.Close()
		}
		requestDone <- err
	}()

	containerID := waitForSingleArenaContainerForTest(t)
	t.Cleanup(func() { removeVerifiedArenaContainerForTest(t, containerID) })
	if err := first.command.Process.Signal(syscall.SIGKILL); err != nil && !strings.Contains(err.Error(), "process already finished") {
		t.Fatalf("terminate first controller: %v", err)
	}
	if err := first.command.Wait(); err != nil {
		if _, ok := err.(*exec.ExitError); !ok {
			t.Fatalf("wait for terminated first controller: %v", err)
		}
	}

	second := startControllerProcessForTest(t, controllerBinary)
	defer stopControllerProcessForTest(t, second)
	select {
	case err := <-requestDone:
		if err == nil {
			t.Fatal("execution request unexpectedly completed after controller termination")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("execution request did not finish after controller termination")
	}
	assertNoArenaContainersForTest(t)
}

type controllerProcessForTest struct {
	command *exec.Cmd
}

func buildControllerBinaryForTest(t *testing.T) string {
	t.Helper()
	_, sourceFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("find integration test source directory")
	}
	sandboxRoot := filepath.Dir(filepath.Dir(filepath.Dir(sourceFile)))
	binary := filepath.Join(t.TempDir(), "arena-controller")
	command := exec.Command("go", "build", "-o", binary, "./cmd/controller")
	command.Dir = sandboxRoot
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build controller test binary: %v", sanitizeDockerTestError(err, output))
	}
	return binary
}

func ensureControllerPortAvailable(t *testing.T) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:8001")
	if err != nil {
		t.Fatalf("controller loopback port is unavailable: %v", err)
	}
	if err := listener.Close(); err != nil {
		t.Fatalf("release controller loopback port: %v", err)
	}
}

func startControllerProcessForTest(t *testing.T, binary string) *controllerProcessForTest {
	t.Helper()
	process := &controllerProcessForTest{command: exec.Command(binary)}
	if err := process.command.Start(); err != nil {
		t.Fatalf("start controller process: %v", err)
	}
	t.Cleanup(func() { stopControllerProcessForTest(t, process) })
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		response, err := http.Get("http://127.0.0.1:8001/health")
		if err == nil {
			response.Body.Close()
			if response.StatusCode == http.StatusOK {
				return process
			}
		}
		if process.command.ProcessState != nil {
			t.Fatal("controller process exited before health check succeeded")
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("controller health check did not succeed")
	return nil
}

func stopControllerProcessForTest(t *testing.T, process *controllerProcessForTest) {
	t.Helper()
	if process == nil || process.command.Process == nil || process.command.ProcessState != nil {
		return
	}
	if err := process.command.Process.Signal(syscall.SIGKILL); err != nil && !strings.Contains(err.Error(), "process already finished") {
		t.Errorf("terminate controller test process: %v", err)
	}
	if err := process.command.Wait(); err != nil {
		if _, ok := err.(*exec.ExitError); !ok {
			t.Errorf("wait for controller test process: %v", err)
		}
	}
}

func waitForSingleArenaContainerForTest(t *testing.T) string {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		output, err := exec.Command("docker", "ps", "--quiet", "--filter", "label="+executor.ArenaOwnershipLabel+"=true").Output()
		if err != nil {
			t.Fatalf("list active Arena tasks: %v", err)
		}
		identifiers := strings.Fields(string(output))
		if len(identifiers) == 1 {
			return identifiers[0]
		}
		if len(identifiers) > 1 {
			t.Fatalf("active Arena task count = %d, want 1", len(identifiers))
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("active Arena task was not created before timeout")
	return ""
}

func removeVerifiedArenaContainerForTest(t *testing.T, containerID string) {
	t.Helper()
	format := "{{.Name}}\t{{index .Config.Labels \"" + executor.ArenaOwnershipLabel + "\"}}\t{{index .Config.Labels \"" + executor.ArenaTaskIDLabel + "\"}}"
	output, err := exec.Command("docker", "inspect", "--format", format, containerID).Output()
	if err != nil {
		return
	}
	parts := strings.Split(strings.TrimSpace(string(output)), "\t")
	if len(parts) != 3 || parts[1] != "true" || !strings.HasPrefix(parts[2], "arena-task-") || parts[0] != "/"+parts[2] {
		return
	}
	if output, err := exec.Command("docker", "rm", "--force", containerID).CombinedOutput(); err != nil {
		t.Errorf("remove verified Arena cleanup container %q: %v", containerID, sanitizeDockerTestError(err, output))
	}
}

func TestRunnerRealDockerPassesJSONStandardInputAndOutput(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	result := runner.Execute(context.Background(), protocol.ExecuteRequest{
		APIVersion: protocol.ExecutionAPIV2,
		RuntimeID:  runtimeconfig.Python311V1,
		Source: `
import json
import sys
value = json.loads(sys.stdin.read())
print(json.dumps({"sum": value["a"] + value["b"]}))
`,
		StdinInput: `{"a":5,"b":3}`,
		IOProtocol: protocol.JSONStdioV1,
	}, pythonRuntime(t))
	if result.ExitReason != protocol.ExitReasonCompleted {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCompleted)
	}
	if !strings.Contains(result.Stdout, `"sum": 8`) && !strings.Contains(result.Stdout, `"sum":8`) {
		t.Fatal("expected JSON stdout result was absent")
	}
	assertNoArenaContainersForTest(t)
}

func TestRunnerRealDockerEnforcesSharedOutputLimitAcrossStreams(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	cases := []struct {
		name string
		code string
	}{
		{name: "stderr", code: `import sys; sys.stderr.write("x" * (70 * 1024))`},
		{name: "combined", code: `import sys; sys.stdout.write("x" * (40 * 1024)); sys.stderr.write("y" * (40 * 1024))`},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			result := runner.Execute(context.Background(), request(testCase.code), pythonRuntime(t))
			if result.ExitReason != protocol.ExitReasonOutputLimitExceeded {
				t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonOutputLimitExceeded)
			}
			if got := len([]byte(result.Stdout)) + len([]byte(result.Stderr)); got != protocol.MaxOutputBytes {
				t.Fatalf("retained output bytes = %d, want %d", got, protocol.MaxOutputBytes)
			}
			assertNoArenaContainersForTest(t)
		})
	}
}

func TestRunnerRealDockerStopsTimeoutWithinWallClockBudget(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	started := time.Now()
	result := runner.Execute(context.Background(), request(`import time; time.sleep(10)`), pythonRuntime(t))
	elapsed := time.Since(started)
	if result.ExitReason != protocol.ExitReasonTimeout {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonTimeout)
	}
	if elapsed > timeoutResponseDeadline {
		t.Fatalf("timeout elapsed = %s, want at most %s including cleanup", elapsed, timeoutResponseDeadline)
	}
	assertNoArenaContainersForTest(t)
}

func TestRunnerRealDockerEnforcesNetworkFilesystemAndUserBoundaries(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	code := `
import os
import socket
import sys

checks = []
try:
    socket.create_connection(("1.1.1.1", 53), timeout=1)
    checks.append("network-open")
except OSError:
    checks.append("network-blocked")
try:
    open("/root-write-check", "w").write("x")
    checks.append("root-writable")
except OSError:
    checks.append("root-readonly")
try:
    open("/tmp/write-check", "w").write("x")
    checks.append("tmp-writable")
except OSError:
    checks.append("tmp-unwritable")
checks.append("non-root" if os.geteuid() != 0 else "root-user")
status = open("/proc/self/status").read()
checks.append("capabilities-dropped" if "CapEff:\t0000000000000000" in status else "capabilities-present")
checks.append("no-new-privileges" if "NoNewPrivs:\t1" in status else "new-privileges-allowed")
print("|".join(checks))
`
	result := runner.Execute(context.Background(), request(code), pythonRuntime(t))
	if result.ExitReason != protocol.ExitReasonCompleted {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCompleted)
	}
	for _, expected := range []string{"network-blocked", "root-readonly", "tmp-writable", "non-root", "capabilities-dropped", "no-new-privileges"} {
		if !strings.Contains(result.Stdout, expected) {
			t.Fatalf("expected isolation evidence %q was absent", expected)
		}
	}
	assertNoArenaContainersForTest(t)
}

func TestRunnerRealDockerEnforcesTmpfsLimit(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	code := `
try:
    block = b"x" * (1024 * 1024)
    with open("/tmp/fill", "wb") as output:
        for _ in range(65):
            output.write(block)
    print("tmpfs-unlimited")
except OSError:
    print("tmpfs-limited")
`
	result := runner.Execute(context.Background(), request(code), pythonRuntime(t))
	if result.ExitReason != protocol.ExitReasonCompleted {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCompleted)
	}
	if !strings.Contains(result.Stdout, "tmpfs-limited") {
		t.Fatal("expected tmpfs-limited evidence was absent")
	}
	assertNoArenaContainersForTest(t)
}

func TestRunnerRealDockerEnforcesPIDLimit(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	code := `
import os
import time

children = []
try:
    for _ in range(64):
        child = os.fork()
        if child == 0:
            time.sleep(1)
            os._exit(0)
        children.append(child)
    print("pid-unlimited")
except OSError:
    print("pid-limited")
finally:
    for child in children:
        try:
            os.waitpid(child, 0)
        except ChildProcessError:
            pass
`
	result := runner.Execute(context.Background(), request(code), pythonRuntime(t))
	if result.ExitReason != protocol.ExitReasonCompleted {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCompleted)
	}
	if !strings.Contains(result.Stdout, "pid-limited") {
		t.Fatal("expected pid-limited evidence was absent")
	}
	assertNoArenaContainersForTest(t)
}

func TestHTTPServerRejectsConcurrentRealDockerExecution(t *testing.T) {
	server := httpapi.NewServer(executor.NewRunner(executor.NewDockerCLI()))
	body := `{"api_version":"execution-api-v2","runtime_id":"python-3.11-v1","source":"import time; time.sleep(3)","stdin_input":"{}","io_protocol":"json-stdio-v1"}`
	firstDone := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		response := httptest.NewRecorder()
		server.Handler().ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(body)))
		firstDone <- response
	}()

	time.Sleep(300 * time.Millisecond)
	second := httptest.NewRecorder()
	server.Handler().ServeHTTP(second, httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(body)))
	if second.Code != http.StatusConflict {
		t.Fatalf("second request status = %d, want %d", second.Code, http.StatusConflict)
	}
	first := <-firstDone
	if first.Code != http.StatusOK {
		t.Fatalf("first request status = %d, want %d", first.Code, http.StatusOK)
	}
	assertNoArenaContainersForTest(t)
}

func TestHTTPServerCancelsDisconnectedRealDockerExecution(t *testing.T) {
	server := httpapi.NewServer(executor.NewRunner(executor.NewDockerCLI()))
	requestContext, cancel := context.WithCancel(context.Background())
	body := `{"api_version":"execution-api-v2","runtime_id":"python-3.11-v1","source":"import time; time.sleep(10)","stdin_input":"{}","io_protocol":"json-stdio-v1"}`
	response := httptest.NewRecorder()
	done := make(chan struct{})
	go func() {
		defer close(done)
		request := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(body)).WithContext(requestContext)
		server.Handler().ServeHTTP(response, request)
	}()

	time.Sleep(300 * time.Millisecond)
	cancel()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("cancelled request did not finish")
	}
	if response.Code != http.StatusOK {
		t.Fatalf("response status = %d, want %d", response.Code, http.StatusOK)
	}
	var result protocol.ExecuteResult
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatalf("response JSON error = %v", err)
	}
	if result.ExitReason != protocol.ExitReasonCancelled {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCancelled)
	}
	assertNoArenaContainersForTest(t)
}

func TestRunnerReportsReliableOOMEvidenceWhenDockerProvidesIt(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	result := runner.Execute(context.Background(), request(`payload = bytearray(256 * 1024 * 1024); print(len(payload))`), pythonRuntime(t))
	if result.ExitReason != protocol.ExitReasonMemoryLimitExceeded || !result.OOMKilled {
		t.Skipf("Docker did not provide stable OOM evidence; exit_reason=%q oom_killed=%t", result.ExitReason, result.OOMKilled)
	}
	assertNoArenaContainersForTest(t)
}

func request(code string) protocol.ExecuteRequest {
	return protocol.ExecuteRequest{APIVersion: protocol.ExecutionAPIV2, RuntimeID: runtimeconfig.Python311V1, Source: code, StdinInput: "{}", IOProtocol: protocol.JSONStdioV1}
}

func pythonRuntime(t *testing.T) runtimeconfig.Config {
	t.Helper()
	config, err := runtimeconfig.NewRegistry().Resolve(runtimeconfig.Python311V1)
	if err != nil {
		t.Fatal(err)
	}
	return config
}

func assertNoArenaContainersForTest(t *testing.T) {
	t.Helper()
	if err := assertNoArenaContainers(); err != nil {
		t.Fatal(err)
	}
}

func assertNoArenaArtifactVolumesForTest(t *testing.T) {
	t.Helper()
	output, err := exec.Command("docker", "volume", "ls", "--quiet", "--filter", "label="+executor.ArenaOwnershipLabel+"=true").Output()
	if err != nil {
		t.Fatal(err)
	}
	if identifiers := strings.Fields(string(output)); len(identifiers) != 0 {
		encoded, _ := json.Marshal(identifiers)
		t.Fatalf("Arena-labelled artifact volumes remain after integration test: %s", encoded)
	}
}

func assertNoArenaContainers() error {
	command := exec.Command("docker", "ps", "-aq", "--filter", "label="+executor.ArenaOwnershipLabel+"=true")
	output, err := command.Output()
	if err != nil {
		return err
	}
	if identifiers := strings.Fields(string(output)); len(identifiers) != 0 {
		encoded, _ := json.Marshal(identifiers)
		return &arenaContainerError{identifiers: string(encoded)}
	}
	return nil
}

func removeVerifiedArenaTaskForTest(t *testing.T, taskID string) {
	t.Helper()
	labels, err := exec.Command("docker", "inspect", "--format", "{{index .Config.Labels \""+executor.ArenaOwnershipLabel+"\"}}:{{index .Config.Labels \""+executor.ArenaTaskIDLabel+"\"}}", taskID).Output()
	if err != nil || strings.TrimSpace(string(labels)) != "true:"+taskID {
		return
	}
	if output, err := exec.Command("docker", "rm", "--force", taskID).CombinedOutput(); err != nil {
		t.Errorf("remove verified Arena cleanup task %q: %v", taskID, sanitizeDockerTestError(err, output))
	}
}

func sanitizeDockerTestError(err error, output []byte) error {
	if len(output) == 0 {
		return err
	}
	return fmt.Errorf("%v: docker command failed", err)
}

type arenaContainerError struct {
	identifiers string
}

func (err *arenaContainerError) Error() string {
	return "Arena-labelled containers remain after integration test: " + err.identifiers
}
