// Package executor defines the contract for running user-supplied scripts
// in a sandboxed subprocess and translating the OS-level result into a
// stable JSON-friendly value.
package executor

import (
	"context"
	"errors"
)

// Runtime identifies which interpreter to use.
type Runtime string

const (
	RuntimeBash       Runtime = "bash"
	RuntimePowershell Runtime = "powershell"
	RuntimePython     Runtime = "python"
)

// Request is the validated input passed to an Executor.
type Request struct {
	ScriptID   string            `json:"script_id"`
	Runtime    Runtime           `json:"runtime"`
	Body       string            `json:"body"`
	TimeoutMs  int               `json:"timeout_ms"`
	Parameters map[string]string `json:"parameters"`
}

// Result is the value returned from an executor after a script has run
// (or has been killed because of a timeout).
type Result struct {
	ExitCode        int    `json:"exit_code"`
	Stdout          string `json:"stdout"`
	Stderr          string `json:"stderr"`
	ExecutionTimeMs int64  `json:"execution_time_ms"`
	TimedOut        bool   `json:"timed_out"`
}

// Executor abstracts how a script body is materialised on disk and
// executed by an interpreter. Implementations must guarantee that:
//   - the script body never appears in process arguments,
//   - the temp file (if any) is removed before returning,
//   - the context deadline is honoured (kills the process group).
type Executor interface {
	Runtime() Runtime
	Execute(ctx context.Context, req Request) (Result, error)
}

// ErrUnsupportedRuntime is returned when a runtime is not enabled on the
// host instance.
var ErrUnsupportedRuntime = errors.New("unsupported runtime")
