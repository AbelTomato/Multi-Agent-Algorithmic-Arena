package httpapi

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"sync"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
)

const maxRequestBodyBytes = protocol.MaxCodeBytes + protocol.MaxInputBytes + 4096

type Executor interface {
	Execute(context.Context, protocol.ExecuteRequest) protocol.ExecuteResult
}

type ExecutorFunc func(context.Context, protocol.ExecuteRequest) protocol.ExecuteResult

func (function ExecutorFunc) Execute(ctx context.Context, request protocol.ExecuteRequest) protocol.ExecuteResult {
	return function(ctx, request)
}

type Server struct {
	executor Executor
	slot     chan struct{}
	mux      *http.ServeMux
	root     context.Context
	cancel   context.CancelFunc
	mu       sync.RWMutex
	closing  bool
}

type executeRequestBody struct {
	Code            *string `json:"code"`
	StdinInput      *string `json:"stdin_input"`
	ProtocolVersion *string `json:"protocol_version"`
}

func NewServer(executor Executor) *Server {
	root, cancel := context.WithCancel(context.Background())
	server := &Server{executor: executor, slot: make(chan struct{}, 1), mux: http.NewServeMux(), root: root, cancel: cancel}
	server.mux.HandleFunc("GET /health", server.health)
	server.mux.HandleFunc("POST /execute", server.execute)
	return server
}

func (server *Server) Handler() http.Handler { return server.mux }

func (server *Server) Shutdown() {
	server.mu.Lock()
	if !server.closing {
		server.closing = true
		server.cancel()
	}
	server.mu.Unlock()
}

func (server *Server) health(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, map[string]string{"status": "ok", "service": "sandbox"})
}

func (server *Server) execute(writer http.ResponseWriter, request *http.Request) {
	server.mu.RLock()
	closing := server.closing
	server.mu.RUnlock()
	if closing {
		writeJSON(writer, http.StatusServiceUnavailable, map[string]string{"detail": "execution controller is shutting down"})
		return
	}
	select {
	case server.slot <- struct{}{}:
		defer func() { <-server.slot }()
	default:
		writeJSON(writer, http.StatusConflict, map[string]string{"detail": "execution slot is busy"})
		return
	}

	request.Body = http.MaxBytesReader(writer, request.Body, maxRequestBodyBytes)
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()
	var body executeRequestBody
	if err := decoder.Decode(&body); err != nil || decoder.Decode(&struct{}{}) != io.EOF {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"detail": "invalid execution request"})
		return
	}
	if body.Code == nil || body.StdinInput == nil || body.ProtocolVersion == nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"detail": "invalid execution request"})
		return
	}
	executeRequest := protocol.ExecuteRequest{
		Code:            *body.Code,
		StdinInput:      *body.StdinInput,
		ProtocolVersion: *body.ProtocolVersion,
	}
	if err := executeRequest.Validate(); err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"detail": "invalid execution request"})
		return
	}
	executionContext, cancel := context.WithCancel(request.Context())
	defer cancel()
	go func() {
		select {
		case <-server.root.Done():
			cancel()
		case <-executionContext.Done():
		}
	}()
	writeJSON(writer, http.StatusOK, server.executor.Execute(executionContext, executeRequest))
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}
