package executor

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os/exec"
	"strings"
	"sync"
)

type DockerCLI struct {
	command commandFactory
}

func NewDockerCLI() *DockerCLI {
	return newDockerCLIForCommand(func(ctx context.Context, args ...string) *exec.Cmd {
		return exec.CommandContext(ctx, "docker", args...)
	})
}

type commandFactory func(context.Context, ...string) *exec.Cmd

func newDockerCLIForCommand(command commandFactory) *DockerCLI {
	return &DockerCLI{command: command}
}

func (docker *DockerCLI) Run(ctx context.Context, args []string, stdin []byte, collector *OutputCollector) (int, InspectResult, error) {
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
	docker.cleanupOwned(taskID)
	if err == nil {
		return 0, inspect, nil
	}
	var exitError *exec.ExitError
	if errors.As(err, &exitError) {
		return exitError.ExitCode(), inspect, nil
	}
	return 0, inspect, err
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

func (docker *DockerCLI) cleanupOwned(taskID string) {
	labels, err := docker.command(context.Background(), "inspect", "--format", "{{index .Config.Labels \""+ArenaOwnershipLabel+"\"}}:{{index .Config.Labels \""+ArenaTaskIDLabel+"\"}}", taskID).Output()
	if err != nil || strings.TrimSpace(string(labels)) != "true:"+taskID {
		return
	}
	_ = docker.command(context.Background(), "stop", "--time", "0", taskID).Run()
	_ = docker.command(context.Background(), "rm", "--force", taskID).Run()
}

func taskIDFromRunArgs(args []string) (string, bool) {
	for index := 0; index+1 < len(args); index++ {
		if args[index] == "--name" && strings.HasPrefix(args[index+1], "arena-task-") {
			return args[index+1], true
		}
	}
	return "", false
}
