// Package sandbox provides the OS-level process plumbing for safely
// running an external interpreter against a script file. It is shared
// by the bash, powershell, and python executors.
//
// Security notes:
//   - The script body is never passed as a command-line argument –
//     callers must materialise it to a temp file (caller responsibility)
//     and pass only the path to the interpreter.
//   - Each child process is started in a fresh process group so that a
//     timeout-triggered kill takes down any sub-processes the script
//     spawned.
//   - Parameters are injected as environment variables prefixed
//     SCRIPT_PARAM_, never as command-line arguments.
package sandbox

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"strings"
	"time"
)

// MaxOutputBytes caps stdout/stderr captured from the child to prevent
// memory exhaustion from a runaway script.
const MaxOutputBytes = 1 << 20 // 1 MiB

// Outcome carries the OS-level result of a sandboxed execution.
type Outcome struct {
	ExitCode        int
	Stdout          string
	Stderr          string
	ExecutionTimeMs int64
	TimedOut        bool
}

// limitedBuffer is a bytes.Buffer that stops accepting input once it
// has reached its cap, so we never let a runaway script fill memory.
type limitedBuffer struct {
	buf bytes.Buffer
	cap int
}

func (l *limitedBuffer) Write(p []byte) (int, error) {
	remaining := l.cap - l.buf.Len()
	if remaining <= 0 {
		return len(p), nil
	}
	if len(p) > remaining {
		p = p[:remaining]
	}
	return l.buf.Write(p)
}

func (l *limitedBuffer) String() string { return l.buf.String() }

// Run executes the supplied binary with arguments and returns a typed
// Outcome. The provided context controls the hard timeout. Parameters
// are injected as SCRIPT_PARAM_<KEY> environment variables.
func Run(ctx context.Context, binary string, args []string, parameters map[string]string) (Outcome, error) {
	if binary == "" {
		return Outcome{}, fmt.Errorf("binary path is required")
	}
	resolved, err := exec.LookPath(binary)
	if err != nil {
		return Outcome{}, fmt.Errorf("interpreter %q not found in PATH: %w", binary, err)
	}

	stdout := &limitedBuffer{cap: MaxOutputBytes}
	stderr := &limitedBuffer{cap: MaxOutputBytes}

	cmd := exec.CommandContext(ctx, resolved, args...)
	cmd.Stdout = stdout
	cmd.Stderr = stderr
	cmd.Stdin = nil

	// Provide a minimal environment plus the parameter injections.
	cmd.Env = buildEnv(parameters)

	startProcessGroup(cmd)

	started := time.Now()
	err = cmd.Run()
	elapsed := time.Since(started)
	timedOut := ctx.Err() == context.DeadlineExceeded

	// Best-effort group kill in case CommandContext leaves descendants.
	if cmd.Process != nil {
		killProcessGroup(cmd)
	}

	exitCode := 0
	if err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			exitCode = exitErr.ExitCode()
		} else if timedOut {
			exitCode = -1
		} else {
			// Errors that aren't ExitError still surface through stderr;
			// keep a non-zero exit but don't propagate the error so the
			// caller can map the outcome consistently.
			exitCode = -1
			if stderr.buf.Len() == 0 {
				_, _ = io.WriteString(&stderr.buf, err.Error())
			}
		}
	}

	return Outcome{
		ExitCode:        exitCode,
		Stdout:          stdout.String(),
		Stderr:          stderr.String(),
		ExecutionTimeMs: elapsed.Milliseconds(),
		TimedOut:        timedOut,
	}, nil
}

// buildEnv assembles the env passed to the child. We intentionally start
// from an empty slice and add only the variables the script needs, so we
// don't leak the parent process's full environment.
func buildEnv(parameters map[string]string) []string {
	env := make([]string, 0, len(parameters)+2)
	// PATH is needed for nested interpreter lookups (e.g. python calling /usr/bin/env).
	env = append(env, "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
	env = append(env, "LANG=C.UTF-8")
	for k, v := range parameters {
		if k == "" {
			continue
		}
		safeKey := sanitizeParamKey(k)
		env = append(env, "SCRIPT_PARAM_"+safeKey+"="+v)
	}
	return env
}

// sanitizeParamKey strips characters that are not allowed in shell
// variable names so we never produce a malformed env entry.
func sanitizeParamKey(k string) string {
	var sb strings.Builder
	for _, r := range k {
		switch {
		case r >= 'A' && r <= 'Z':
			sb.WriteRune(r)
		case r >= 'a' && r <= 'z':
			sb.WriteRune(r - 32) // upper-case
		case r >= '0' && r <= '9':
			sb.WriteRune(r)
		case r == '_':
			sb.WriteRune(r)
		default:
			sb.WriteRune('_')
		}
	}
	return sb.String()
}

