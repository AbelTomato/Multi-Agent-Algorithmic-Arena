package executor

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestDockerCLICleansVerifiedTaskAfterSuccessfulExecution(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "docker-cli.log")
	t.Setenv("ARENA_DOCKER_HELPER", "1")
	t.Setenv("ARENA_DOCKER_HELPER_LOG", logPath)
	docker := newDockerCLIForCommand(testDockerCommand)
	collector := NewOutputCollector(64 * 1024)
	taskID := "arena-task-unit"

	exitCode, inspect, err := docker.Run(context.Background(), []string{"run", "--name", taskID}, nil, collector)
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if exitCode != 0 || inspect.OOMKilled {
		t.Fatalf("Run() = (%d, %#v), want (0, non-OOM)", exitCode, inspect)
	}
	if got := collector.Stdout(); got != "ok" {
		t.Fatalf("stdout = %q, want %q", got, "ok")
	}

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("ReadFile() error = %v", err)
	}
	got := strings.Fields(string(content))
	want := []string{"run", "inspect-state", "inspect-labels", "stop", "rm"}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("CLI calls = %v, want %v", got, want)
	}
}

func TestDockerCLIRecoversListedOwnedTask(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "docker-cli-recovery.log")
	t.Setenv("ARENA_DOCKER_HELPER", "1")
	t.Setenv("ARENA_DOCKER_HELPER_LOG", logPath)
	docker := newDockerCLIForCommand(testDockerCommand)

	if err := RecoverStaleTasks(context.Background(), docker); err != nil {
		t.Fatalf("RecoverStaleTasks() error = %v", err)
	}

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("ReadFile() error = %v", err)
	}
	got := strings.Fields(string(content))
	want := []string{"ps", "inspect-recovery", "stop", "rm"}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("CLI calls = %v, want %v", got, want)
	}
}

func TestDockerCLIListsManagedTasksWithFullContainerIdentifiers(t *testing.T) {
	var arguments []string
	docker := newDockerCLIForCommand(func(ctx context.Context, args ...string) *exec.Cmd {
		arguments = append([]string(nil), args...)
		return testDockerCommand(ctx, args...)
	})

	if _, err := docker.ListManagedTasks(context.Background()); err != nil {
		t.Fatalf("ListManagedTasks() error = %v", err)
	}
	if !containsArgument(arguments, "--no-trunc") {
		t.Fatalf("ListManagedTasks() arguments = %#v, want --no-trunc", arguments)
	}
}

func containsArgument(arguments []string, expected string) bool {
	for _, argument := range arguments {
		if argument == expected {
			return true
		}
	}
	return false
}

func testDockerCommand(ctx context.Context, args ...string) *exec.Cmd {
	commandArgs := append([]string{"-test.run=TestDockerCLIHelperProcess", "--"}, args...)
	return exec.CommandContext(ctx, os.Args[0], commandArgs...)
}

func TestDockerCLIHelperProcess(t *testing.T) {
	if os.Getenv("ARENA_DOCKER_HELPER") != "1" {
		return
	}
	args := os.Args
	separator := 0
	for index, arg := range args {
		if arg == "--" {
			separator = index + 1
			break
		}
	}
	if separator == 0 || separator >= len(args) {
		os.Exit(2)
	}
	command := args[separator]
	logCommand(command)
	switch command {
	case "run":
		_, _ = io.WriteString(os.Stdout, "ok")
	case "ps":
		_, _ = io.WriteString(os.Stdout, "container-unit\n")
	case "inspect":
		format := strings.Join(args[separator:], " ")
		if strings.Contains(format, ".State") {
			_, _ = io.WriteString(os.Stdout, `{"OOMKilled":false}`)
		} else if strings.Contains(format, ".Id") {
			_, _ = io.WriteString(os.Stdout, "container-unit\t/arena-task-container-unit\ttrue\tarena-task-container-unit")
		} else {
			_, _ = io.WriteString(os.Stdout, "true:arena-task-unit")
		}
	case "stop", "rm":
	default:
		os.Exit(3)
	}
	os.Exit(0)
}

func logCommand(command string) {
	path := os.Getenv("ARENA_DOCKER_HELPER_LOG")
	if strings.TrimSpace(path) == "" {
		return
	}
	if command == "inspect" {
		format := strings.Join(os.Args, " ")
		if strings.Contains(format, ".State") {
			command = "inspect-state"
		} else if strings.Contains(format, ".Id") {
			command = "inspect-recovery"
		} else {
			command = "inspect-labels"
		}
	}
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		os.Exit(4)
	}
	defer file.Close()
	_, _ = fmt.Fprintln(file, command)
}
