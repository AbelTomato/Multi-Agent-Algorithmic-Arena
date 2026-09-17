package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/executor"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/httpapi"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
)

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
			result := runner.Execute(context.Background(), request(testCase.code))
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

func TestRunnerRealDockerPassesJSONStandardInputAndOutput(t *testing.T) {
	runner := executor.NewRunner(executor.NewDockerCLI())
	result := runner.Execute(context.Background(), protocol.ExecuteRequest{
		Code: `
import json
import sys
value = json.loads(sys.stdin.read())
print(json.dumps({"sum": value["a"] + value["b"]}))
`,
		StdinInput:      `{"a":5,"b":3}`,
		ProtocolVersion: protocol.JSONStdioV1,
	})
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
			result := runner.Execute(context.Background(), request(testCase.code))
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
	result := runner.Execute(context.Background(), request(`import time; time.sleep(10)`))
	elapsed := time.Since(started)
	if result.ExitReason != protocol.ExitReasonTimeout {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonTimeout)
	}
	if elapsed > 5500*time.Millisecond {
		t.Fatalf("timeout elapsed = %s, want at most 5.5s", elapsed)
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
print("|".join(checks))
`
	result := runner.Execute(context.Background(), request(code))
	if result.ExitReason != protocol.ExitReasonCompleted {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCompleted)
	}
	for _, expected := range []string{"network-blocked", "root-readonly", "tmp-writable", "non-root"} {
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
	result := runner.Execute(context.Background(), request(code))
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
	result := runner.Execute(context.Background(), request(code))
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
	body := `{"code":"import time; time.sleep(3)","stdin_input":"{}","protocol_version":"json-stdio-v1"}`
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
	body := `{"code":"import time; time.sleep(10)","stdin_input":"{}","protocol_version":"json-stdio-v1"}`
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
	result := runner.Execute(context.Background(), request(`payload = bytearray(256 * 1024 * 1024); print(len(payload))`))
	if result.ExitReason != protocol.ExitReasonMemoryLimitExceeded || !result.OOMKilled {
		t.Skipf("Docker did not provide stable OOM evidence; exit_reason=%q oom_killed=%t", result.ExitReason, result.OOMKilled)
	}
	assertNoArenaContainersForTest(t)
}

func request(code string) protocol.ExecuteRequest {
	return protocol.ExecuteRequest{Code: code, StdinInput: "{}", ProtocolVersion: protocol.JSONStdioV1}
}

func assertNoArenaContainersForTest(t *testing.T) {
	t.Helper()
	if err := assertNoArenaContainers(); err != nil {
		t.Fatal(err)
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

type arenaContainerError struct {
	identifiers string
}

func (err *arenaContainerError) Error() string {
	return "Arena-labelled containers remain after integration test: " + err.identifiers
}
