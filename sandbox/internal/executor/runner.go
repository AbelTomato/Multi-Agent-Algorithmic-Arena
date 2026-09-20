package executor

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/runtime"
)

const (
	ArenaOwnershipLabel = "io.arena.sandbox.owner"
	ArenaTaskIDLabel    = "io.arena.sandbox.task-id"
)

type InspectResult struct {
	OOMKilled bool
}

type Docker interface {
	Run(context.Context, []string, []byte, *OutputCollector) (exitCode int, inspect InspectResult, err error)
}

type ArtifactDocker interface {
	CreateArtifactVolume(context.Context, string, string) error
	RemoveArtifactVolume(context.Context, string, string) error
}

type Runner struct {
	docker          Docker
	taskIDGenerator func() (string, error)
}

func NewRunner(docker Docker) *Runner {
	return &Runner{docker: docker, taskIDGenerator: newTaskID}
}

func (runner *Runner) Execute(parent context.Context, request protocol.ExecuteRequest, config runtime.Config) protocol.ExecuteResult {
	started := time.Now()
	if parent.Err() != nil {
		return runner.result(protocol.ExitReasonCancelled, nil, nil, started)
	}
	if err := request.Validate(); err != nil {
		return runner.result(protocol.ExitReasonUnknownError, nil, nil, started)
	}
	if len(config.CompileCommand) > 0 {
		return runner.compileAndExecute(parent, request, config, started)
	}

	executionContext, cancel := context.WithTimeout(parent, config.WallTimeout)
	defer cancel()
	collector := NewOutputCollector(config.MaxOutputBytes)
	taskID, err := runner.taskIDGenerator()
	if err != nil {
		return runner.result(protocol.ExitReasonUnknownError, nil, collector, started)
	}
	exitCode, inspect, err := runner.docker.Run(executionContext, runner.BuildDockerRunArgs(taskID, config, request.Source), []byte(request.StdinInput), collector)
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

func (runner *Runner) compileAndExecute(parent context.Context, request protocol.ExecuteRequest, config runtime.Config, started time.Time) protocol.ExecuteResult {
	artifacts, ok := runner.docker.(ArtifactDocker)
	if !ok {
		return runner.result(protocol.ExitReasonDockerError, nil, nil, started)
	}
	taskID, err := runner.taskIDGenerator()
	if err != nil {
		return runner.result(protocol.ExitReasonUnknownError, nil, nil, started)
	}
	volumeID := taskID + "-artifact"
	if err := artifacts.CreateArtifactVolume(parent, volumeID, taskID); err != nil {
		return runner.result(protocol.ExitReasonDockerError, nil, nil, started)
	}
	defer artifacts.RemoveArtifactVolume(context.Background(), volumeID, taskID)

	compileCollector := NewOutputCollector(config.MaxOutputBytes)
	compileContext, cancelCompile := context.WithTimeout(parent, config.CompileWallTimeout)
	defer cancelCompile()
	initializeArgs := runner.BuildArtifactInitializationArgs(taskID+"-init", volumeID, config)
	if _, _, err := runner.docker.Run(compileContext, initializeArgs, nil, compileCollector); err != nil {
		return runner.result(protocol.ExitReasonDockerError, nil, compileCollector, started)
	}
	compileArgs := runner.BuildCompileDockerRunArgs(taskID+"-compile", volumeID, config)
	compileCode, compileInspect, compileErr := runner.docker.Run(compileContext, compileArgs, []byte(request.Source), compileCollector)
	if compileCollector.Exceeded() {
		return runner.result(protocol.ExitReasonCompilationOLE, protocol.Int(compileCode), compileCollector, started)
	}
	if parent.Err() != nil {
		return runner.result(protocol.ExitReasonCancelled, nil, compileCollector, started)
	}
	if compileContext.Err() == context.DeadlineExceeded {
		return runner.result(protocol.ExitReasonCompilationTimeout, nil, compileCollector, started)
	}
	if compileErr != nil {
		return runner.result(protocol.ExitReasonDockerError, nil, compileCollector, started)
	}
	if compileInspect.OOMKilled {
		return runner.result(protocol.ExitReasonMemoryLimitExceeded, protocol.Int(compileCode), compileCollector, started, true)
	}
	if compileCode != 0 {
		return runner.result(protocol.ExitReasonCompilationFailed, protocol.Int(compileCode), compileCollector, started)
	}

	executionContext, cancelExecution := context.WithTimeout(parent, config.WallTimeout)
	defer cancelExecution()
	runCollector := NewOutputCollector(config.MaxOutputBytes)
	runCode, runInspect, runErr := runner.docker.Run(executionContext, runner.BuildCompiledProgramRunArgs(taskID, volumeID, config), []byte(request.StdinInput), runCollector)
	if runCollector.Exceeded() {
		return runner.result(protocol.ExitReasonOutputLimitExceeded, protocol.Int(runCode), runCollector, started)
	}
	if parent.Err() != nil {
		return runner.result(protocol.ExitReasonCancelled, nil, runCollector, started)
	}
	if executionContext.Err() == context.DeadlineExceeded {
		return runner.result(protocol.ExitReasonTimeout, nil, runCollector, started)
	}
	if runErr != nil {
		return runner.result(protocol.ExitReasonDockerError, nil, runCollector, started)
	}
	classified := Classify(runCode, runInspect)
	return runner.result(classified.ExitReason, protocol.Int(runCode), runCollector, started, classified.OOMKilled)
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

func (runner *Runner) BuildDockerRunArgs(taskID string, config runtime.Config, source string) []string {
	args := []string{
		"run", "--name", taskID, "--label", ArenaOwnershipLabel + "=true",
		"--label", ArenaTaskIDLabel + "=" + taskID, "--network", config.NetworkMode,
	}
	if config.ReadOnly {
		args = append(args, "--read-only")
	}
	args = append(args,
		"--tmpfs", config.Tmpfs, "--user", config.User, "--cpus", config.CPUs, "--memory", config.Memory,
		"--memory-swap", config.MemorySwap, "--pids-limit", config.PIDsLimit, "--cap-drop", config.CapDrop,
	)
	if config.NoNewPrivileges {
		args = append(args, "--security-opt", "no-new-privileges")
	}
	return append(args, "-i", config.Image, config.Command[0], config.Command[1], source)
}

func (runner *Runner) BuildArtifactInitializationArgs(taskID, volumeID string, config runtime.Config) []string {
	args := runner.buildDockerBaseArgs(taskID, config)
	return append(args, "--cap-add", "CHOWN", "--read-only", "--user", "0:0", "--mount", "type=volume,src="+volumeID+",dst=/arena/out", "-i", config.Image, "sh", "-c", "mkdir -p /arena/out && chown 65534:65534 /arena/out")
}

func (runner *Runner) BuildCompileDockerRunArgs(taskID, volumeID string, config runtime.Config) []string {
	args := runner.buildDockerBaseArgs(taskID, config)
	args = append(args, "--read-only", "--tmpfs", config.CompileTmpfs, "--user", config.User, "--memory", config.CompileMemory, "--memory-swap", config.CompileMemorySwap, "--mount", "type=volume,src="+volumeID+",dst=/arena/out", "-i", config.Image)
	args = append(args, "sh", "-c", "cat > /arena/out/main.cpp && \"$@\" && test -x /arena/out/program", "compile")
	return append(args, config.CompileCommand...)
}

func (runner *Runner) BuildCompiledProgramRunArgs(taskID, volumeID string, config runtime.Config) []string {
	args := runner.buildDockerBaseArgs(taskID, config)
	args = append(args, "--read-only", "--tmpfs", config.Tmpfs, "--user", config.User, "--memory", config.Memory, "--memory-swap", config.MemorySwap, "--mount", "type=volume,src="+volumeID+",dst=/arena/out,readonly", "-i", config.Image)
	return append(args, config.CompiledProgram)
}

func (runner *Runner) buildDockerBaseArgs(taskID string, config runtime.Config) []string {
	args := []string{"run", "--name", taskID, "--label", ArenaOwnershipLabel + "=true", "--label", ArenaTaskIDLabel + "=" + taskID, "--network", config.NetworkMode, "--cpus", config.CPUs, "--pids-limit", config.PIDsLimit, "--cap-drop", config.CapDrop}
	if config.NoNewPrivileges {
		args = append(args, "--security-opt", "no-new-privileges")
	}
	return args
}

func newTaskID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return "arena-task-" + hex.EncodeToString(buffer), nil
}
