package executor

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/runtime"
)

const defaultAuditLogPath = "arena-sandbox-audit.jsonl"

type RuntimeAudit struct {
	Event            string `json:"event"`
	Timestamp        string `json:"timestamp"`
	TaskID           string `json:"task_id"`
	RuntimeImage     string `json:"runtime_image"`
	NetworkMode      string `json:"network_mode"`
	ReadOnly         bool   `json:"read_only"`
	Tmpfs            string `json:"tmpfs"`
	User             string `json:"user"`
	CPUs             string `json:"cpus"`
	Memory           string `json:"memory"`
	MemorySwap       string `json:"memory_swap"`
	PIDsLimit        string `json:"pids_limit"`
	CapDrop          string `json:"cap_drop"`
	NoNewPrivileges  bool   `json:"no_new_privileges"`
	WallTimeoutMS    int64  `json:"wall_timeout_ms"`
	ExitCode         *int   `json:"exit_code,omitempty"`
	OOMKilled        bool   `json:"oom_killed"`
	RunOutcome       string `json:"run_outcome"`
	CleanupCompleted bool   `json:"cleanup_completed"`
	ExecutionWallMS  int64  `json:"execution_wall_ms"`
}

// AuditLogger writes fixed-field, newline-delimited JSON records. It never accepts
// candidate code, standard input, standard output, standard error, or environment data.
type AuditLogger struct {
	path string
	mu   sync.Mutex
}

func NewAuditLogger(path string) (*AuditLogger, error) {
	if path == "" {
		path = defaultAuditLogPath
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return nil, fmt.Errorf("create sandbox audit directory: %w", err)
	}
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o640)
	if err != nil {
		return nil, fmt.Errorf("open sandbox audit log: %w", err)
	}
	if err := file.Close(); err != nil {
		return nil, fmt.Errorf("close sandbox audit log: %w", err)
	}
	return &AuditLogger{path: path}, nil
}

func (logger *AuditLogger) Write(record RuntimeAudit) error {
	payload, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("encode sandbox audit record: %w", err)
	}

	logger.mu.Lock()
	defer logger.mu.Unlock()
	file, err := os.OpenFile(logger.path, os.O_APPEND|os.O_WRONLY, 0o640)
	if err != nil {
		return fmt.Errorf("open sandbox audit log: %w", err)
	}
	defer file.Close()
	if _, err := file.Write(append(payload, '\n')); err != nil {
		return fmt.Errorf("write sandbox audit record: %w", err)
	}
	return nil
}

func newRuntimeAudit(taskID string, config runtime.Config, exitCode *int, inspect InspectResult, runOutcome string, cleanupCompleted bool, started time.Time) RuntimeAudit {
	return RuntimeAudit{
		Event:            "arena_task",
		Timestamp:        time.Now().UTC().Format(time.RFC3339Nano),
		TaskID:           taskID,
		RuntimeImage:     config.Image,
		NetworkMode:      config.NetworkMode,
		ReadOnly:         config.ReadOnly,
		Tmpfs:            config.Tmpfs,
		User:             config.User,
		CPUs:             config.CPUs,
		Memory:           config.Memory,
		MemorySwap:       config.MemorySwap,
		PIDsLimit:        config.PIDsLimit,
		CapDrop:          config.CapDrop,
		NoNewPrivileges:  config.NoNewPrivileges,
		WallTimeoutMS:    config.WallTimeout.Milliseconds(),
		ExitCode:         exitCode,
		OOMKilled:        inspect.OOMKilled,
		RunOutcome:       runOutcome,
		CleanupCompleted: cleanupCompleted,
		ExecutionWallMS:  time.Since(started).Milliseconds(),
	}
}
