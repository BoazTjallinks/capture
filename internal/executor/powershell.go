package executor

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"time"

	"github.com/bluewave-labs/capture/internal/sandbox"
)

// PowerShellExecutor prefers pwsh (PowerShell Core, cross-platform) and
// falls back to powershell.exe on Windows hosts. The script body is
// written to a temp .ps1 file – never passed as -Command.
type PowerShellExecutor struct{}

func NewPowerShellExecutor() *PowerShellExecutor { return &PowerShellExecutor{} }

func (p *PowerShellExecutor) Runtime() Runtime { return RuntimePowershell }

func (p *PowerShellExecutor) Execute(ctx context.Context, req Request) (Result, error) {
	tmp, err := os.CreateTemp("", "checkmate-script-*.ps1")
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

	binary := "pwsh"
	if _, err := exec.LookPath(binary); err != nil {
		binary = "powershell"
	}

	deadline := time.Duration(req.TimeoutMs) * time.Millisecond
	runCtx, cancel := context.WithTimeout(ctx, deadline)
	defer cancel()

	args := []string{"-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", tmpPath}
	outcome, err := sandbox.Run(runCtx, binary, args, req.Parameters)
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
