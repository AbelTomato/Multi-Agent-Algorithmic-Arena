package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/executor"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/httpapi"
)

const (
	defaultListenAddress             = "127.0.0.1:8001"
	listenAddressEnvironmentVariable = "ARENA_SANDBOX_LISTEN_ADDR"
	auditLogEnvironmentVariable      = "ARENA_SANDBOX_AUDIT_LOG"
)

func main() {
	address, err := listenAddress()
	if err != nil {
		log.Fatalf("validate sandbox listen address: %v", err)
	}
	audit, err := executor.NewAuditLogger(strings.TrimSpace(os.Getenv(auditLogEnvironmentVariable)))
	if err != nil {
		log.Fatalf("initialize sandbox audit log: %v", err)
	}
	docker := executor.NewDockerCLIWithAudit(audit)
	if err := executor.RecoverStaleTasks(context.Background(), docker); err != nil {
		log.Fatalf("recover stale Arena tasks before startup: %v", err)
	}
	controller := httpapi.NewServer(executor.NewRunner(docker))
	httpServer := &http.Server{Addr: address, Handler: controller.Handler()}
	go func() {
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal(err)
		}
	}()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)
	<-signals
	controller.Shutdown()
	shutdownContext, cancel := context.WithTimeout(context.Background(), 7*time.Second)
	defer cancel()
	if err := httpServer.Shutdown(shutdownContext); err != nil {
		log.Printf("controller shutdown error: %v", err)
	}
}

func listenAddress() (string, error) {
	address := strings.TrimSpace(os.Getenv(listenAddressEnvironmentVariable))
	if address == "" {
		return defaultListenAddress, nil
	}

	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return "", fmt.Errorf("parse %s: %w", listenAddressEnvironmentVariable, err)
	}
	if port != "8001" {
		return "", fmt.Errorf("%s must use port 8001", listenAddressEnvironmentVariable)
	}
	ip := net.ParseIP(host)
	if ip == nil || ip.To4() == nil || (!ip.IsLoopback() && !ip.IsPrivate()) {
		return "", fmt.Errorf("%s must use a loopback or private IPv4 address", listenAddressEnvironmentVariable)
	}
	return address, nil
}
