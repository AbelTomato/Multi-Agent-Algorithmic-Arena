package executor

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"strings"
	"sync"
	"time"
)

type DockerCLI struct {
	command commandFactory
	audit   *AuditLogger
}

func NewDockerCLI() *DockerCLI {
	return newDockerCLIForCommand(func(ctx context.Context, args ...string) *exec.Cmd {
		return exec.CommandContext(ctx, "docker", args...)
	})
}

func NewDockerCLIWithAudit(audit *AuditLogger) *DockerCLI {
	return newDockerCLIForCommandWithAudit(func(ctx context.Context, args ...string) *exec.Cmd {
		return exec.CommandContext(ctx, "docker", args...)
	}, audit)
}

type commandFactory func(context.Context, ...string) *exec.Cmd

func newDockerCLIForCommand(command commandFactory) *DockerCLI {
	return newDockerCLIForCommandWithAudit(command, nil)
}

func newDockerCLIForCommandWithAudit(command commandFactory, audit *AuditLogger) *DockerCLI {
	return &DockerCLI{command: command, audit: audit}
}

func (docker *DockerCLI) Run(ctx context.Context, args []string, stdin []byte, collector *OutputCollector) (int, InspectResult, error) {
	started := time.Now()
	taskID, ok := taskIDFromRunArgs(args)
	if !ok {
		return 0, InspectResult{}, errors.New("missing managed task ID")
	}

	commandContext, cancelCommand := context.WithCancel(ctx)
	defer cancelCommand()
	command := docker.command(commandContext, args...)
	command.Stdin = bytes.NewReader(stdin)
	stdout, err := command.StdoutPipe()
	if err != nil {
		return 0, InspectResult{}, err
	}
	stderr, err := command.StderrPipe()
	if err != nil {
		return 0, InspectResult{}, err
	}
	if err := command.Start(); err != nil {
		return 0, InspectResult{}, err
	}

	var readers sync.WaitGroup
	readers.Add(2)
	go copyOutput(&readers, stdout, collector.WriteStdout, cancelCommand)
	go copyOutput(&readers, stderr, collector.WriteStderr, cancelCommand)
	err = command.Wait()
	readers.Wait()

	inspect := docker.inspectOwned(taskID)
	cleanupCompleted := docker.cleanupOwned(taskID)
	if err == nil {
		return docker.finishAuditedRun(taskID, 0, inspect, "completed", cleanupCompleted, started)
	}
	var exitError *exec.ExitError
	if errors.As(err, &exitError) {
		return docker.finishAuditedRun(taskID, exitError.ExitCode(), inspect, "non_zero_exit", cleanupCompleted, started)
	}
	if auditErr := docker.writeAudit(taskID, nil, inspect, "docker_error", cleanupCompleted, started); auditErr != nil {
		return 0, inspect, auditErr
	}
	return 0, inspect, err
}

func (docker *DockerCLI) finishAuditedRun(taskID string, exitCode int, inspect InspectResult, outcome string, cleanupCompleted bool, started time.Time) (int, InspectResult, error) {
	if err := docker.writeAudit(taskID, &exitCode, inspect, outcome, cleanupCompleted, started); err != nil {
		return 0, inspect, err
	}
	return exitCode, inspect, nil
}

func (docker *DockerCLI) writeAudit(taskID string, exitCode *int, inspect InspectResult, outcome string, cleanupCompleted bool, started time.Time) error {
	if docker.audit == nil {
		return nil
	}
	return docker.audit.Write(newRuntimeAudit(taskID, exitCode, inspect, outcome, cleanupCompleted, started))
}

func copyOutput(readers *sync.WaitGroup, source io.Reader, write func([]byte) bool, cancel context.CancelFunc) {
	defer readers.Done()
	buffer := make([]byte, 4096)
	for {
		count, err := source.Read(buffer)
		if count > 0 && write(buffer[:count]) {
			cancel()
			return
		}
		if err != nil {
			return
		}
	}
}

func (docker *DockerCLI) inspectOwned(taskID string) InspectResult {
	output, err := docker.command(context.Background(), "inspect", "--format", "{{json .State}}", taskID).Output()
	if err != nil {
		return InspectResult{}
	}
	var state struct {
		OOMKilled bool `json:"OOMKilled"`
	}
	if err := json.Unmarshal(output, &state); err != nil {
		return InspectResult{}
	}
	return InspectResult{OOMKilled: state.OOMKilled}
}

func (docker *DockerCLI) cleanupOwned(taskID string) bool {
	labels, err := docker.command(context.Background(), "inspect", "--format", "{{index .Config.Labels \""+ArenaOwnershipLabel+"\"}}:{{index .Config.Labels \""+ArenaTaskIDLabel+"\"}}", taskID).Output()
	if err != nil || strings.TrimSpace(string(labels)) != "true:"+taskID {
		return false
	}
	stopErr := docker.command(context.Background(), "stop", "--time", "0", taskID).Run()
	removeErr := docker.command(context.Background(), "rm", "--force", taskID).Run()
	return stopErr == nil && removeErr == nil
}

func (docker *DockerCLI) ListManagedTasks(ctx context.Context) ([]ManagedTask, error) {
	output, err := docker.command(ctx, "ps", "--all", "--quiet", "--no-trunc", "--filter", "label="+ArenaOwnershipLabel+"=true").Output()
	if err != nil {
		return nil, err
	}
	identifiers := strings.Fields(string(output))
	tasks := make([]ManagedTask, 0, len(identifiers))
	for _, identifier := range identifiers {
		tasks = append(tasks, ManagedTask{ContainerID: identifier})
	}
	return tasks, nil
}

func (docker *DockerCLI) InspectManagedTask(ctx context.Context, containerID string) (ManagedTask, error) {
	format := "{{.Id}}\t{{.Name}}\t{{index .Config.Labels \"" + ArenaOwnershipLabel + "\"}}\t{{index .Config.Labels \"" + ArenaTaskIDLabel + "\"}}"
	output, err := docker.command(ctx, "inspect", "--format", format, containerID).Output()
	if err != nil {
		return ManagedTask{}, normalizeManagedTaskError(err)
	}
	parts := strings.Split(strings.TrimSpace(string(output)), "\t")
	if len(parts) != 4 || strings.TrimSpace(parts[0]) == "" {
		return ManagedTask{}, errors.New("invalid managed task inspection output")
	}
	return ManagedTask{
		ContainerID: parts[0],
		Name:        parts[1],
		Owner:       parts[2] == "true",
		TaskID:      parts[3],
	}, nil
}

func (docker *DockerCLI) StopManagedTask(ctx context.Context, containerID string) error {
	return normalizeManagedTaskError(docker.command(ctx, "stop", "--time", "0", containerID).Run())
}

func (docker *DockerCLI) RemoveManagedTask(ctx context.Context, containerID string) error {
	return normalizeManagedTaskError(docker.command(ctx, "rm", "--force", containerID).Run())
}

func normalizeManagedTaskError(err error) error {
	if err == nil {
		return nil
	}
	message := err.Error()
	var exitError *exec.ExitError
	if errors.As(err, &exitError) {
		message += " " + string(exitError.Stderr)
	}
	message = strings.ToLower(message)
	if strings.Contains(message, "no such container") || strings.Contains(message, "not found") {
		return fmt.Errorf("%w: %v", ErrManagedTaskNotFound, err)
	}
	return err
}

func taskIDFromRunArgs(args []string) (string, bool) {
	for index := 0; index+1 < len(args); index++ {
		if args[index] == "--name" && strings.HasPrefix(args[index+1], "arena-task-") {
			return args[index+1], true
		}
	}
	return "", false
}
