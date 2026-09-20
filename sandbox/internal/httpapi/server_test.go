package httpapi

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/runtime"
)

type blockingExecutor struct {
	started chan struct{}
	release chan struct{}
	once    sync.Once
}

func (executor *blockingExecutor) Execute(ctx context.Context, request protocol.ExecuteRequest, config runtime.Config) protocol.ExecuteResult {
	executor.once.Do(func() { close(executor.started) })
	select {
	case <-executor.release:
		return protocol.ExecuteResult{ExitReason: protocol.ExitReasonCompleted, ExitCode: protocol.Int(0)}
	case <-ctx.Done():
		return protocol.ExecuteResult{ExitReason: protocol.ExitReasonCancelled}
	}
}

func TestExecuteRejectsUnknownFields(t *testing.T) {
	server := NewServer(ExecutorFunc(func(context.Context, protocol.ExecuteRequest, runtime.Config) protocol.ExecuteResult {
		return protocol.ExecuteResult{ExitReason: protocol.ExitReasonCompleted, ExitCode: protocol.Int(0)}
	}))

	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(`{"api_version":"execution-api-v2","runtime_id":"python-3.11-v1","source":"print(1)","stdin_input":"{}","io_protocol":"json-stdio-v1","task_id":"client-controlled"}`))
	server.Handler().ServeHTTP(response, request)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadRequest)
	}
}

func TestExecuteRejectsMissingRequiredFields(t *testing.T) {
	server := NewServer(ExecutorFunc(func(context.Context, protocol.ExecuteRequest, runtime.Config) protocol.ExecuteResult {
		return protocol.ExecuteResult{ExitReason: protocol.ExitReasonCompleted, ExitCode: protocol.Int(0)}
	}))

	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(`{"api_version":"execution-api-v2","runtime_id":"python-3.11-v1","source":"print(1)","io_protocol":"json-stdio-v1"}`))
	server.Handler().ServeHTTP(response, request)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadRequest)
	}
}

func TestExecuteRejectsUnknownRuntimeBeforeExecutor(t *testing.T) {
	called := false
	server := NewServer(ExecutorFunc(func(context.Context, protocol.ExecuteRequest, runtime.Config) protocol.ExecuteResult {
		called = true
		return protocol.ExecuteResult{ExitReason: protocol.ExitReasonCompleted, ExitCode: protocol.Int(0)}
	}))
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(`{"api_version":"execution-api-v2","runtime_id":"unknown-v1","source":"print(1)","stdin_input":"{}","io_protocol":"json-stdio-v1"}`))
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest || called {
		t.Fatalf("status = %d, executor called = %t; want 400 and no executor call", response.Code, called)
	}
}

func TestExecuteRejectsUnsupportedIOProtocolBeforeExecutor(t *testing.T) {
	called := false
	server := NewServer(ExecutorFunc(func(context.Context, protocol.ExecuteRequest, runtime.Config) protocol.ExecuteResult {
		called = true
		return protocol.ExecuteResult{ExitReason: protocol.ExitReasonCompleted, ExitCode: protocol.Int(0)}
	}))
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(`{"api_version":"execution-api-v2","runtime_id":"python-3.11-v1","source":"print(1)","stdin_input":"{}","io_protocol":"shell-v1"}`))
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest || called {
		t.Fatalf("status = %d, executor called = %t; want 400 and no executor call", response.Code, called)
	}
}

func TestExecuteRejectsSecondRequestWhileSlotIsHeld(t *testing.T) {
	executor := &blockingExecutor{started: make(chan struct{}), release: make(chan struct{})}
	server := NewServer(executor)
	body := `{"api_version":"execution-api-v2","runtime_id":"python-3.11-v1","source":"print(1)","stdin_input":"{}","io_protocol":"json-stdio-v1"}`

	firstResponse := httptest.NewRecorder()
	firstRequest := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(body))
	firstDone := make(chan struct{})
	go func() {
		defer close(firstDone)
		server.Handler().ServeHTTP(firstResponse, firstRequest)
	}()

	select {
	case <-executor.started:
	case <-time.After(time.Second):
		t.Fatal("first execution did not start")
	}

	secondResponse := httptest.NewRecorder()
	secondRequest := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(body))
	server.Handler().ServeHTTP(secondResponse, secondRequest)
	if secondResponse.Code != http.StatusConflict {
		t.Fatalf("second status = %d, want %d", secondResponse.Code, http.StatusConflict)
	}

	close(executor.release)
	select {
	case <-firstDone:
	case <-time.After(time.Second):
		t.Fatal("first execution did not finish")
	}

	thirdResponse := httptest.NewRecorder()
	thirdRequest := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(body))
	server.Handler().ServeHTTP(thirdResponse, thirdRequest)
	if thirdResponse.Code != http.StatusOK {
		t.Fatalf("third status = %d, want %d", thirdResponse.Code, http.StatusOK)
	}
}

func TestShutdownCancelsActiveExecutionAndReleasesSlot(t *testing.T) {
	executor := &blockingExecutor{started: make(chan struct{}), release: make(chan struct{})}
	server := NewServer(executor)
	body := `{"api_version":"execution-api-v2","runtime_id":"python-3.11-v1","source":"print(1)","stdin_input":"{}","io_protocol":"json-stdio-v1"}`

	firstResponse := httptest.NewRecorder()
	firstRequest := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(body))
	firstDone := make(chan struct{})
	go func() {
		defer close(firstDone)
		server.Handler().ServeHTTP(firstResponse, firstRequest)
	}()
	select {
	case <-executor.started:
	case <-time.After(time.Second):
		t.Fatal("first execution did not start")
	}

	server.Shutdown()
	select {
	case <-firstDone:
	case <-time.After(time.Second):
		t.Fatal("active execution was not cancelled during shutdown")
	}

	secondResponse := httptest.NewRecorder()
	secondRequest := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewBufferString(body))
	server.Handler().ServeHTTP(secondResponse, secondRequest)
	if secondResponse.Code != http.StatusServiceUnavailable {
		t.Fatalf("status after shutdown = %d, want %d", secondResponse.Code, http.StatusServiceUnavailable)
	}
}
