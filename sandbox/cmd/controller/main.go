package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/executor"
	"github.com/AbelTomato/Multi-Agent-Algorithmic-Arena/sandbox/internal/httpapi"
)

func main() {
	controller := httpapi.NewServer(executor.NewRunner(executor.NewDockerCLI()))
	httpServer := &http.Server{Addr: "127.0.0.1:8001", Handler: controller.Handler()}
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
