package protocol

import (
	"errors"
	"strings"
)

const (
	JSONStdioV1    = "json-stdio-v1"
	MaxCodeBytes   = 64 * 1024
	MaxInputBytes  = 64 * 1024
	MaxOutputBytes = 64 * 1024
)

type ExitReason string

const (
	ExitReasonCompleted           ExitReason = "completed"
	ExitReasonNonZeroExit         ExitReason = "non_zero_exit"
	ExitReasonTimeout             ExitReason = "timeout"
	ExitReasonOutputLimitExceeded ExitReason = "output_limit_exceeded"
	ExitReasonCancelled           ExitReason = "cancelled"
	ExitReasonDockerError         ExitReason = "docker_error"
	ExitReasonUnknownError        ExitReason = "unknown_error"
	ExitReasonMemoryLimitExceeded ExitReason = "memory_limit_exceeded"
)

type ExecuteRequest struct {
	Code            string `json:"code"`
	StdinInput      string `json:"stdin_input"`
	ProtocolVersion string `json:"protocol_version"`
}

func (request ExecuteRequest) Validate() error {
	if request.ProtocolVersion != JSONStdioV1 {
		return errors.New("unsupported protocol_version")
	}
	if strings.TrimSpace(request.Code) == "" {
		return errors.New("code must not be blank")
	}
	if len([]byte(request.Code)) > MaxCodeBytes {
		return errors.New("code exceeds byte limit")
	}
	if len([]byte(request.StdinInput)) > MaxInputBytes {
		return errors.New("stdin_input exceeds byte limit")
	}
	return nil
}

type ExecuteResult struct {
	ExitReason ExitReason `json:"exit_reason"`
	ExitCode   *int       `json:"exit_code,omitempty"`
	Stdout     string     `json:"stdout"`
	Stderr     string     `json:"stderr"`
	WallTimeMS int64      `json:"wall_time_ms"`
	OOMKilled  bool       `json:"oom_killed"`
}

func Int(value int) *int { return &value }
