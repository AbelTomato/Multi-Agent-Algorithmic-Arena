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

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/runtime"
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

func TestDockerCLICreatesAndRemovesOnlyVerifiedArtifactVolume(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "docker-cli-volume.log")
	t.Setenv("ARENA_DOCKER_HELPER", "1")
	t.Setenv("ARENA_DOCKER_HELPER_LOG", logPath)
	docker := newDockerCLIForCommand(testDockerCommand)
	taskID := "arena-task-artifact"
	volumeID := taskID + "-artifact"

	if err := docker.CreateArtifactVolume(context.Background(), volumeID, taskID); err != nil {
		t.Fatalf("CreateArtifactVolume() error = %v", err)
	}
	if err := docker.RemoveArtifactVolume(context.Background(), volumeID, taskID); err != nil {
		t.Fatalf("RemoveArtifactVolume() error = %v", err)
	}

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("ReadFile() error = %v", err)
	}
	got := strings.Fields(string(content))
	want := []string{"volume-create", "volume-inspect", "volume-rm"}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("CLI calls = %v, want %v", got, want)
	}
}

func TestDockerCLIWritesSanitizedRuntimeAuditAfterCleanup(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "sandbox-audit.jsonl")
	t.Setenv("ARENA_DOCKER_HELPER", "1")
	t.Setenv("ARENA_DOCKER_HELPER_LOG", filepath.Join(t.TempDir(), "docker-cli.log"))
	audit, err := NewAuditLogger(logPath)
	if err != nil {
		t.Fatalf("NewAuditLogger() error = %v", err)
	}
	docker := newDockerCLIForCommandWithAudit(testDockerCommand, audit)
	taskID := "arena-task-audited"
	candidateCode := "print('candidate-secret')"

	exitCode, inspect, err := docker.Run(
		context.Background(),
		[]string{
			"run", "--name", taskID,
			"--label", ArenaOwnershipLabel + "=true",
			"--label", ArenaTaskIDLabel + "=" + taskID,
			"--network", "none", "--read-only",
			"--tmpfs", "/tmp:size=64m,noexec", "--user", "65534:65534",
			"--cpus", "1", "--memory", "128m", "--memory-swap", "128m",
			"--pids-limit", "32", "--cap-drop", "ALL",
			"--security-opt", "no-new-privileges", "-i", mustRuntimeImage(t),
			"python3", "-c", candidateCode,
		},
		[]byte(`{"secret":"stdin-secret"}`),
		NewOutputCollector(64*1024),
	)
	if err != nil || exitCode != 0 || inspect.OOMKilled {
		t.Fatalf("Run() = (%d, %#v, %v), want successful non-OOM execution", exitCode, inspect, err)
	}

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("ReadFile() error = %v", err)
	}
	line := strings.TrimSpace(string(content))
	for _, forbidden := range []string{"candidate-secret", "stdin-secret", "stdout", "stderr", "api_key", "password"} {
		if strings.Contains(line, forbidden) {
			t.Fatalf("audit record contains forbidden value %q: %s", forbidden, line)
		}
	}
	for _, required := range []string{"\"event\":\"arena_task\"", "\"task_id\":\"arena-task-audited\"", "\"network_mode\":\"none\"", "\"read_only\":true", "\"cleanup_completed\":true", "\"runtime_image\":"} {
		if !strings.Contains(line, required) {
			t.Fatalf("audit record missing %q: %s", required, line)
		}
	}
}

func TestDockerCLIAuditsCppRuntimeImageFromTrustedRunArgs(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "sandbox-cpp-audit.jsonl")
	t.Setenv("ARENA_DOCKER_HELPER", "1")
	audit, err := NewAuditLogger(logPath)
	if err != nil {
		t.Fatalf("NewAuditLogger() error = %v", err)
	}
	docker := newDockerCLIForCommandWithAudit(testDockerCommand, audit)
	config, err := runtime.NewRegistry().Resolve(runtime.CppGcc14Cpp20V1)
	if err != nil {
		t.Fatal(err)
	}
	taskID := "arena-task-cpp-audit"
	args := NewRunner(nil).BuildCompiledProgramRunArgs(taskID, taskID+"-artifact", config)

	if _, _, err := docker.Run(context.Background(), args, nil, NewOutputCollector(64*1024)); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("ReadFile() error = %v", err)
	}
	if !strings.Contains(string(content), `"runtime_image":"`+config.Image+`"`) {
		t.Fatalf("audit record = %s, want C++ runtime image %q", content, config.Image)
	}
}

func mustRuntimeImage(t *testing.T) string {
	t.Helper()
	config, err := runtime.NewRegistry().Resolve(runtime.Python311V1)
	if err != nil {
		t.Fatal(err)
	}
	return config.Image
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
	if command == "volume" && separator+1 < len(args) {
		logCommand("volume-" + args[separator+1])
	} else {
		logCommand(command)
	}
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
			_, _ = io.WriteString(os.Stdout, "true:"+args[len(args)-1])
		}
	case "stop", "rm":
	case "volume":
		if separator+1 >= len(args) {
			os.Exit(2)
		}
		switch args[separator+1] {
		case "create":
			_, _ = io.WriteString(os.Stdout, args[separator+3]+"\n")
		case "inspect":
			volumeID := args[len(args)-1]
			taskID := strings.TrimSuffix(volumeID, "-artifact")
			_, _ = io.WriteString(os.Stdout, "true:"+taskID)
		case "rm":
		default:
			os.Exit(3)
		}
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
