package httpapi

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"sync"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/protocol"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/runtime"
)

const maxRequestBodyBytes = protocol.MaxSourceBytes + protocol.MaxInputBytes + 4096

type Executor interface {
	Execute(context.Context, protocol.ExecuteRequest, runtime.Config) protocol.ExecuteResult
}

type ExecutorFunc func(context.Context, protocol.ExecuteRequest, runtime.Config) protocol.ExecuteResult

func (function ExecutorFunc) Execute(ctx context.Context, request protocol.ExecuteRequest, config runtime.Config) protocol.ExecuteResult {
	return function(ctx, request, config)
}

type Server struct {
	executor Executor
	slot     chan struct{}
	mux      *http.ServeMux
	root     context.Context
	cancel   context.CancelFunc
	registry *runtime.Registry
	mu       sync.RWMutex
	closing  bool
}

func NewServer(executor Executor) *Server {
	return NewServerWithRegistry(executor, runtime.NewRegistry())
}

func NewServerWithRegistry(executor Executor, registry *runtime.Registry) *Server {
	root, cancel := context.WithCancel(context.Background())
	server := &Server{executor: executor, slot: make(chan struct{}, 1), mux: http.NewServeMux(), root: root, cancel: cancel, registry: registry}
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
	body, err := io.ReadAll(request.Body)
	if err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"detail": "invalid execution request"})
		return
	}
	executeRequest, err := protocol.DecodeExecuteRequest(body)
	if err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"detail": "invalid execution request"})
		return
	}
	config, err := server.registry.Resolve(executeRequest.RuntimeID)
	if err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"detail": "unknown runtime"})
		return
	}
	if !config.SupportsIOProtocol(executeRequest.IOProtocol) {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"detail": "unsupported io_protocol"})
		return
	}
	if len([]byte(executeRequest.Source)) > config.MaxSourceBytes || len([]byte(executeRequest.StdinInput)) > config.MaxInputBytes {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"detail": "execution input exceeds runtime limit"})
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
	writeJSON(writer, http.StatusOK, server.executor.Execute(executionContext, executeRequest, config))
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}
