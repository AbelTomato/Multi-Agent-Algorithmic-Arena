package executor

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

var ErrManagedTaskNotFound = errors.New("managed task not found")

type ManagedTask struct {
	ContainerID string
	Name        string
	Owner       bool
	TaskID      string
}

type RecoveryDocker interface {
	ListManagedTasks(context.Context) ([]ManagedTask, error)
	InspectManagedTask(context.Context, string) (ManagedTask, error)
	StopManagedTask(context.Context, string) error
	RemoveManagedTask(context.Context, string) error
}

func RecoverStaleTasks(ctx context.Context, docker RecoveryDocker) error {
	candidates, err := docker.ListManagedTasks(ctx)
	if err != nil {
		return fmt.Errorf("list stale Arena tasks: %w", err)
	}

	var recoveryErrors []error
	for _, candidate := range candidates {
		task, err := docker.InspectManagedTask(ctx, candidate.ContainerID)
		if err != nil {
			if !errors.Is(err, ErrManagedTaskNotFound) {
				recoveryErrors = append(recoveryErrors, fmt.Errorf("inspect stale Arena task %q: %w", candidate.ContainerID, err))
			}
			continue
		}
		if !isVerifiedManagedTask(candidate.ContainerID, task) {
			continue
		}
		if err := docker.StopManagedTask(ctx, task.ContainerID); err != nil && !errors.Is(err, ErrManagedTaskNotFound) {
			recoveryErrors = append(recoveryErrors, fmt.Errorf("stop stale Arena task %q: %w", task.ContainerID, err))
		}
		if err := docker.RemoveManagedTask(ctx, task.ContainerID); err != nil && !errors.Is(err, ErrManagedTaskNotFound) {
			recoveryErrors = append(recoveryErrors, fmt.Errorf("remove stale Arena task %q: %w", task.ContainerID, err))
		}
	}
	return errors.Join(recoveryErrors...)
}

func isVerifiedManagedTask(candidateID string, task ManagedTask) bool {
	return task.ContainerID == candidateID &&
		task.Owner &&
		strings.HasPrefix(task.TaskID, "arena-task-") &&
		task.Name == "/"+task.TaskID
}
