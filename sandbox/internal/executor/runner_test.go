package executor

import (
	"context"
	"testing"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
)

type fakeDocker struct{}

func (fakeDocker) Run(context.Context, []string, []byte, *OutputCollector) (int, InspectResult, error) {
	return 0, InspectResult{}, nil
}

func TestBuildDockerRunArgsUsesFixedLimitsAndServerTaskID(t *testing.T) {
	runner := NewRunner(fakeDocker{})
	args := runner.BuildDockerRunArgs("arena-task-server-generated", "print(1)")

	want := []string{
		"run", "--name", "arena-task-server-generated", "--label", ArenaOwnershipLabel + "=true",
		"--label", ArenaTaskIDLabel + "=arena-task-server-generated", "--network", "none", "--read-only",
		"--tmpfs", "/tmp:size=64m,noexec", "--user", "65534:65534", "--cpus", "1", "--memory", "128m",
		"--memory-swap", "128m", "--pids-limit", "32", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
		"-i", RuntimeImage, "python3", "-c", "print(1)",
	}
	if len(args) != len(want) {
		t.Fatalf("args = %#v, want %#v", args, want)
	}
	for index := range want {
		if args[index] != want[index] {
			t.Fatalf("args[%d] = %q, want %q", index, args[index], want[index])
		}
	}
}

func TestClassifyExitCode137WithoutOOMIsNotMemoryLimit(t *testing.T) {
	result := Classify(137, InspectResult{OOMKilled: false})
	if result.ExitReason != protocol.ExitReasonNonZeroExit {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonNonZeroExit)
	}
}

func TestClassifyOOMEvidenceIsMemoryLimit(t *testing.T) {
	result := Classify(137, InspectResult{OOMKilled: true})
	if result.ExitReason != protocol.ExitReasonMemoryLimitExceeded {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonMemoryLimitExceeded)
	}
}

func TestSharedOutputCollectorStopsAtCombinedLimit(t *testing.T) {
	collector := NewOutputCollector(5)
	if exceeded := collector.WriteStdout([]byte("abc")); exceeded {
		t.Fatal("stdout unexpectedly exceeded limit")
	}
	if exceeded := collector.WriteStderr([]byte("def")); !exceeded {
		t.Fatal("stderr did not exceed shared limit")
	}
	if got := collector.TotalBytes(); got != 5 {
		t.Fatalf("total bytes = %d, want 5", got)
	}
}

func TestSharedOutputCollectorAcceptsOutputExactlyAtLimit(t *testing.T) {
	collector := NewOutputCollector(5)
	if exceeded := collector.WriteStdout([]byte("abc")); exceeded {
		t.Fatal("stdout unexpectedly exceeded limit")
	}
	if exceeded := collector.WriteStderr([]byte("de")); exceeded {
		t.Fatal("output exactly at limit must not exceed limit")
	}
	if got := collector.TotalBytes(); got != 5 {
		t.Fatalf("total bytes = %d, want 5", got)
	}
}

func TestRunnerReturnsCancelledForCancelledContext(t *testing.T) {
	context, cancel := context.WithCancel(context.Background())
	cancel()
	runner := NewRunner(fakeDocker{})
	result := runner.Execute(context, protocol.ExecuteRequest{Code: "print(1)", StdinInput: "{}", ProtocolVersion: protocol.JSONStdioV1})
	if result.ExitReason != protocol.ExitReasonCancelled {
		t.Fatalf("exit reason = %q, want %q", result.ExitReason, protocol.ExitReasonCancelled)
	}
}
