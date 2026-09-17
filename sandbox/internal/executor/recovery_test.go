package executor

import (
	"context"
	"errors"
	"os/exec"
	"reflect"
	"testing"
)

type recoveryDockerStub struct {
	listed       []ManagedTask
	listErr      error
	inspected    map[string]ManagedTask
	inspectErr   map[string]error
	stopErr      map[string]error
	removeErr    map[string]error
	inspectCalls []string
	stopCalls    []string
	removeCalls  []string
}

func (stub *recoveryDockerStub) ListManagedTasks(context.Context) ([]ManagedTask, error) {
	return stub.listed, stub.listErr
}

func (stub *recoveryDockerStub) InspectManagedTask(_ context.Context, containerID string) (ManagedTask, error) {
	stub.inspectCalls = append(stub.inspectCalls, containerID)
	if err := stub.inspectErr[containerID]; err != nil {
		return ManagedTask{}, err
	}
	return stub.inspected[containerID], nil
}

func (stub *recoveryDockerStub) StopManagedTask(_ context.Context, containerID string) error {
	stub.stopCalls = append(stub.stopCalls, containerID)
	return stub.stopErr[containerID]
}

func (stub *recoveryDockerStub) RemoveManagedTask(_ context.Context, containerID string) error {
	stub.removeCalls = append(stub.removeCalls, containerID)
	return stub.removeErr[containerID]
}

func ownedTask(containerID string) ManagedTask {
	taskID := "arena-task-" + containerID
	return ManagedTask{ContainerID: containerID, Name: "/" + taskID, Owner: true, TaskID: taskID}
}

func TestRecoverStaleTasksStopsAndRemovesOnlyVerifiedOwnedTasks(t *testing.T) {
	verified := ownedTask("verified")
	labelMismatch := ManagedTask{ContainerID: "mismatch", Name: "/arena-task-mismatch", Owner: true, TaskID: "arena-task-other"}
	stub := &recoveryDockerStub{
		listed:    []ManagedTask{verified, labelMismatch},
		inspected: map[string]ManagedTask{verified.ContainerID: verified, labelMismatch.ContainerID: labelMismatch},
	}

	if err := RecoverStaleTasks(context.Background(), stub); err != nil {
		t.Fatalf("RecoverStaleTasks() error = %v", err)
	}
	if !reflect.DeepEqual(stub.inspectCalls, []string{verified.ContainerID, labelMismatch.ContainerID}) {
		t.Fatalf("inspect calls = %#v", stub.inspectCalls)
	}
	if !reflect.DeepEqual(stub.stopCalls, []string{verified.ContainerID}) {
		t.Fatalf("stop calls = %#v, want only verified task", stub.stopCalls)
	}
	if !reflect.DeepEqual(stub.removeCalls, []string{verified.ContainerID}) {
		t.Fatalf("remove calls = %#v, want only verified task", stub.removeCalls)
	}
}

func TestRecoverStaleTasksIgnoresTaskThatDisappearsDuringCleanup(t *testing.T) {
	task := ownedTask("gone")
	stub := &recoveryDockerStub{
		listed:    []ManagedTask{task},
		inspected: map[string]ManagedTask{task.ContainerID: task},
		stopErr:   map[string]error{task.ContainerID: ErrManagedTaskNotFound},
		removeErr: map[string]error{task.ContainerID: ErrManagedTaskNotFound},
	}

	if err := RecoverStaleTasks(context.Background(), stub); err != nil {
		t.Fatalf("RecoverStaleTasks() error = %v, want nil for disappeared task", err)
	}
	if !reflect.DeepEqual(stub.removeCalls, []string{task.ContainerID}) {
		t.Fatalf("remove calls = %#v, want cleanup to continue after missing stop target", stub.removeCalls)
	}
}

func TestRecoverStaleTasksReturnsCleanupFailureOtherThanMissingTask(t *testing.T) {
	task := ownedTask("remove-failure")
	removeFailure := errors.New("daemon unavailable")
	stub := &recoveryDockerStub{
		listed:    []ManagedTask{task},
		inspected: map[string]ManagedTask{task.ContainerID: task},
		removeErr: map[string]error{task.ContainerID: removeFailure},
	}

	err := RecoverStaleTasks(context.Background(), stub)
	if !errors.Is(err, removeFailure) {
		t.Fatalf("RecoverStaleTasks() error = %v, want wrapped %v", err, removeFailure)
	}
}

func TestRecoverStaleTasksReturnsInspectFailure(t *testing.T) {
	task := ownedTask("inspect-failure")
	inspectFailure := errors.New("inspect failed")
	stub := &recoveryDockerStub{
		listed:     []ManagedTask{task},
		inspectErr: map[string]error{task.ContainerID: inspectFailure},
	}

	err := RecoverStaleTasks(context.Background(), stub)
	if !errors.Is(err, inspectFailure) {
		t.Fatalf("RecoverStaleTasks() error = %v, want wrapped %v", err, inspectFailure)
	}
}

func TestRecoverStaleTasksReturnsDockerUnavailableListFailure(t *testing.T) {
	listFailure := errors.New("cannot connect to Docker daemon")
	stub := &recoveryDockerStub{listErr: listFailure}

	err := RecoverStaleTasks(context.Background(), stub)
	if !errors.Is(err, listFailure) {
		t.Fatalf("RecoverStaleTasks() error = %v, want wrapped %v", err, listFailure)
	}
}

func TestRecoverStaleTasksReturnsStopFailureAndStillAttemptsRemoval(t *testing.T) {
	task := ownedTask("stop-failure")
	stopFailure := errors.New("stop failed")
	stub := &recoveryDockerStub{
		listed:    []ManagedTask{task},
		inspected: map[string]ManagedTask{task.ContainerID: task},
		stopErr:   map[string]error{task.ContainerID: stopFailure},
	}

	err := RecoverStaleTasks(context.Background(), stub)
	if !errors.Is(err, stopFailure) {
		t.Fatalf("RecoverStaleTasks() error = %v, want wrapped %v", err, stopFailure)
	}
	if !reflect.DeepEqual(stub.removeCalls, []string{task.ContainerID}) {
		t.Fatalf("remove calls = %#v, want removal after stop failure", stub.removeCalls)
	}
}

func TestNormalizeManagedTaskErrorRecognizesDockerNotFoundStderr(t *testing.T) {
	err := normalizeManagedTaskError(&exec.ExitError{Stderr: []byte("Error response from daemon: No such container: gone")})
	if !errors.Is(err, ErrManagedTaskNotFound) {
		t.Fatalf("normalizeManagedTaskError() = %v, want ErrManagedTaskNotFound", err)
	}
}
