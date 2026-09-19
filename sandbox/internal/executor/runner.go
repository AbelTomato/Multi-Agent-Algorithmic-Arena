package executor

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
)

const (
	RuntimeImage        = "m.daocloud.io/docker.io/library/python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534"
	ArenaOwnershipLabel = "io.arena.sandbox.owner"
	ArenaTaskIDLabel    = "io.arena.sandbox.task-id"
	wallTimeout         = 5 * time.Second
)

type InspectResult struct {
	OOMKilled bool
}

type Docker interface {
	Run(context.Context, []string, []byte, *OutputCollector) (exitCode int, inspect InspectResult, err error)
}

type Runner struct {
	docker          Docker
	taskIDGenerator func() (string, error)
}

func NewRunner(docker Docker) *Runner {
	return &Runner{docker: docker, taskIDGenerator: newTaskID}
}

func (runner *Runner) Execute(parent context.Context, request protocol.ExecuteRequest) protocol.ExecuteResult {
	started := time.Now()
	if parent.Err() != nil {
		return runner.result(protocol.ExitReasonCancelled, nil, nil, started)
	}
	if err := request.Validate(); err != nil {
		return runner.result(protocol.ExitReasonUnknownError, nil, nil, started)
	}

	executionContext, cancel := context.WithTimeout(parent, wallTimeout)
	defer cancel()
	collector := NewOutputCollector(protocol.MaxOutputBytes)
	taskID, err := runner.taskIDGenerator()
	if err != nil {
		return runner.result(protocol.ExitReasonUnknownError, nil, collector, started)
	}
	exitCode, inspect, err := runner.docker.Run(executionContext, runner.BuildDockerRunArgs(taskID, request.Code), []byte(request.StdinInput), collector)
	if collector.Exceeded() {
		return runner.result(protocol.ExitReasonOutputLimitExceeded, protocol.Int(exitCode), collector, started)
	}
	if parent.Err() != nil {
		return runner.result(protocol.ExitReasonCancelled, nil, collector, started)
	}
	if executionContext.Err() == context.DeadlineExceeded {
		return runner.result(protocol.ExitReasonTimeout, nil, collector, started)
	}
	if err != nil {
		return runner.result(protocol.ExitReasonDockerError, nil, collector, started)
	}
	classified := Classify(exitCode, inspect)
	return runner.result(classified.ExitReason, protocol.Int(exitCode), collector, started, classified.OOMKilled)
}

func (runner *Runner) result(reason protocol.ExitReason, exitCode *int, collector *OutputCollector, started time.Time, oomKilled ...bool) protocol.ExecuteResult {
	result := protocol.ExecuteResult{ExitReason: reason, ExitCode: exitCode, WallTimeMS: time.Since(started).Milliseconds()}
	if collector != nil {
		result.Stdout = collector.Stdout()
		result.Stderr = collector.Stderr()
	}
	if len(oomKilled) > 0 {
		result.OOMKilled = oomKilled[0]
	}
	return result
}

type Classification struct {
	ExitReason protocol.ExitReason
	OOMKilled  bool
}

func Classify(exitCode int, inspect InspectResult) Classification {
	if inspect.OOMKilled {
		return Classification{ExitReason: protocol.ExitReasonMemoryLimitExceeded, OOMKilled: true}
	}
	if exitCode == 0 {
		return Classification{ExitReason: protocol.ExitReasonCompleted}
	}
	return Classification{ExitReason: protocol.ExitReasonNonZeroExit}
}

func (runner *Runner) BuildDockerRunArgs(taskID string, code string) []string {
	return []string{
		"run", "--name", taskID, "--label", ArenaOwnershipLabel + "=true",
		"--label", ArenaTaskIDLabel + "=" + taskID, "--network", "none", "--read-only",
		"--tmpfs", "/tmp:size=64m,noexec", "--user", "65534:65534", "--cpus", "1", "--memory", "128m",
		"--memory-swap", "128m", "--pids-limit", "32", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
		"-i", RuntimeImage, "python3", "-c", code,
	}
}

func newTaskID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return "arena-task-" + hex.EncodeToString(buffer), nil
}
