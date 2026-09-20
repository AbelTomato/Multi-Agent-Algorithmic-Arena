package protocol

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

const (
	ExecutionAPIV2 = "execution-api-v2"
	JSONStdioV1    = "json-stdio-v1"
	MaxSourceBytes = 64 * 1024
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
	ExitReasonCompilationFailed   ExitReason = "compilation_failed"
	ExitReasonCompilationTimeout  ExitReason = "compilation_timeout"
	ExitReasonCompilationOLE      ExitReason = "compilation_output_limit_exceeded"
)

type ExecuteRequest struct {
	APIVersion string `json:"api_version"`
	RuntimeID  string `json:"runtime_id"`
	Source     string `json:"source"`
	StdinInput string `json:"stdin_input"`
	IOProtocol string `json:"io_protocol"`
}

func (request ExecuteRequest) Validate() error {
	if request.APIVersion != ExecutionAPIV2 {
		return errors.New("unsupported api_version")
	}
	if strings.TrimSpace(request.RuntimeID) == "" {
		return errors.New("runtime_id must not be blank")
	}
	if strings.TrimSpace(request.Source) == "" {
		return errors.New("source must not be blank")
	}
	if len([]byte(request.Source)) > MaxSourceBytes {
		return errors.New("source exceeds byte limit")
	}
	if len([]byte(request.StdinInput)) > MaxInputBytes {
		return errors.New("stdin_input exceeds byte limit")
	}
	if strings.TrimSpace(request.IOProtocol) == "" {
		return errors.New("io_protocol must not be blank")
	}
	return nil
}

type requestPayload struct {
	APIVersion *string `json:"api_version"`
	RuntimeID  *string `json:"runtime_id"`
	Source     *string `json:"source"`
	StdinInput *string `json:"stdin_input"`
	IOProtocol *string `json:"io_protocol"`
}

func DecodeExecuteRequest(data []byte) (ExecuteRequest, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var payload requestPayload
	if err := decoder.Decode(&payload); err != nil {
		return ExecuteRequest{}, fmt.Errorf("decode execution request: %w", err)
	}
	if err := ensureEnd(decoder); err != nil {
		return ExecuteRequest{}, err
	}
	if payload.APIVersion == nil || payload.RuntimeID == nil || payload.Source == nil || payload.StdinInput == nil || payload.IOProtocol == nil {
		return ExecuteRequest{}, errors.New("missing required execution field")
	}
	request := ExecuteRequest{
		APIVersion: *payload.APIVersion,
		RuntimeID:  *payload.RuntimeID,
		Source:     *payload.Source,
		StdinInput: *payload.StdinInput,
		IOProtocol: *payload.IOProtocol,
	}
	if err := request.Validate(); err != nil {
		return ExecuteRequest{}, err
	}
	return request, nil
}

func ensureEnd(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		if err == nil {
			return errors.New("multiple JSON values are not allowed")
		}
		return fmt.Errorf("decode trailing execution request: %w", err)
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
