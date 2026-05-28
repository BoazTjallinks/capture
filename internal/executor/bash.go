package executor

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/bluewave-labs/capture/internal/sandbox"
)

// BashExecutor materialises a script body to a temp file, then runs
// /bin/bash (or whatever the host resolves bash to) against that file.
// The script body is never passed on the command line.
type BashExecutor struct{}

func NewBashExecutor() *BashExecutor { return &BashExecutor{} }

func (b *BashExecutor) Runtime() Runtime { return RuntimeBash }

func (b *BashExecutor) Execute(ctx context.Context, req Request) (Result, error) {
	tmp, err := os.CreateTemp("", "checkmate-script-*.sh")
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
	if err := os.Chmod(tmpPath, 0o600); err != nil {
		return Result{}, fmt.Errorf("failed to chmod temp file: %w", err)
	}

	deadline := time.Duration(req.TimeoutMs) * time.Millisecond
	runCtx, cancel := context.WithTimeout(ctx, deadline)
	defer cancel()

	outcome, err := sandbox.Run(runCtx, "bash", []string{tmpPath}, req.Parameters)
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
