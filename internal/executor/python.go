package executor

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"time"

	"github.com/bluewave-labs/capture/internal/sandbox"
)

// PythonExecutor writes the script to a temp .py file and executes it
// via python3 (preferred) or python. Never uses -c to avoid argv length
// limits and injection risk.
type PythonExecutor struct{}

func NewPythonExecutor() *PythonExecutor { return &PythonExecutor{} }

func (p *PythonExecutor) Runtime() Runtime { return RuntimePython }

func (p *PythonExecutor) Execute(ctx context.Context, req Request) (Result, error) {
	tmp, err := os.CreateTemp("", "checkmate-script-*.py")
	if err != nil {
		return Result{}, fmt.Errorf("failed to create temp file: %w", err)
	}
	tmpPath := tmp.Name()
	defer func() {
		_ = os.Remove(tmpPath)
	}()
	if _, err := tmp.WriteString(req.Body); err != nil {
		_ = tmp.Close()
		return Result{}, fmt.Errorf("failed to write script body: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return Result{}, fmt.Errorf("failed to close temp file: %w", err)
	}

	binary := "python3"
	if _, err := exec.LookPath(binary); err != nil {
		binary = "python"
	}

	deadline := time.Duration(req.TimeoutMs) * time.Millisecond
	runCtx, cancel := context.WithTimeout(ctx, deadline)
	defer cancel()

	outcome, err := sandbox.Run(runCtx, binary, []string{tmpPath}, req.Parameters)
	if err != nil {
		return Result{}, err
	}
	return Result{
		ExitCode:        outcome.ExitCode,
		Stdout:          outcome.Stdout,
		Stderr:          outcome.Stderr,
		ExecutionTimeMs: outcome.ExecutionTimeMs,
		TimedOut:        outcome.TimedOut,
	}, nil
}
