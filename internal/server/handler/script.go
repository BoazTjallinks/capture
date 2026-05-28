package handler

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"github.com/bluewave-labs/capture/internal/executor"
	"github.com/bluewave-labs/capture/internal/limiter"
	"github.com/gin-gonic/gin"
)

// ScriptRequest is the inbound JSON shape for POST /api/v1/script.
type ScriptRequest struct {
	ScriptID   string            `json:"script_id"`
	Runtime    string            `json:"runtime" binding:"required"`
	Body       string            `json:"body" binding:"required"`
	TimeoutMs  int               `json:"timeout_ms"`
	Parameters map[string]string `json:"parameters"`
}

// ScriptResponse is the outbound JSON shape returned by /api/v1/script.
type ScriptResponse struct {
	ExitCode        int    `json:"exit_code"`
	Stdout          string `json:"stdout"`
	Stderr          string `json:"stderr"`
	ExecutionTimeMs int64  `json:"execution_time_ms"`
	TimedOut        bool   `json:"timed_out"`
}

// ScriptHandler dispatches a validated request to the appropriate
// executor, enforcing the concurrency limit.
type ScriptHandler struct {
	limiter         *limiter.Limiter
	executors       map[executor.Runtime]executor.Executor
	allowedRuntimes map[executor.Runtime]struct{}
}

// NewScriptHandler builds a handler with the given allowed runtimes.
// Disallowed runtimes are rejected with 400.
func NewScriptHandler(maxConcurrent, maxQueue int, allowedRuntimes []string) *ScriptHandler {
	allowed := map[executor.Runtime]struct{}{}
	for _, r := range allowedRuntimes {
		allowed[executor.Runtime(strings.ToLower(strings.TrimSpace(r)))] = struct{}{}
	}
	return &ScriptHandler{
		limiter: limiter.New(maxConcurrent, maxQueue),
		executors: map[executor.Runtime]executor.Executor{
			executor.RuntimeBash:       executor.NewBashExecutor(),
			executor.RuntimePowershell: executor.NewPowerShellExecutor(),
			executor.RuntimePython:     executor.NewPythonExecutor(),
		},
		allowedRuntimes: allowed,
	}
}

// MaxScriptBodyBytes is the upper limit on the inbound script body to
// mirror the Checkmate server-side cap.
const MaxScriptBodyBytes = 64 * 1024

func (h *ScriptHandler) Execute(c *gin.Context) {
	var req ScriptRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if len(req.Body) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "script body is required"})
		return
	}
	if len(req.Body) > MaxScriptBodyBytes {
		c.JSON(http.StatusBadRequest, gin.H{"error": "script body exceeds maximum size"})
		return
	}
	if strings.IndexByte(req.Body, 0) != -1 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "script body contains forbidden null bytes"})
		return
	}

	runtime := executor.Runtime(strings.ToLower(strings.TrimSpace(req.Runtime)))
	if _, ok := h.allowedRuntimes[runtime]; !ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": "runtime not permitted on this agent"})
		return
	}
	exec, ok := h.executors[runtime]
	if !ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": "unknown runtime"})
		return
	}

	timeoutMs := req.TimeoutMs
	if timeoutMs <= 0 {
		timeoutMs = 30000
	}
	if timeoutMs > 300000 {
		timeoutMs = 300000
	}

	// Concurrency control.
	ctx := c.Request.Context()
	if err := h.limiter.Acquire(ctx); err != nil {
		if errors.Is(err, limiter.ErrCapacityExceeded) {
			c.JSON(http.StatusTooManyRequests, gin.H{"error": "execution queue is full"})
			return
		}
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "agent shutting down"})
		return
	}
	defer h.limiter.Release()

	execCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	result, err := exec.Execute(execCtx, executor.Request{
		ScriptID:   req.ScriptID,
		Runtime:    runtime,
		Body:       req.Body,
		TimeoutMs:  timeoutMs,
		Parameters: req.Parameters,
	})
	if err != nil {
		// Never echo back the script body or full error stack to the caller.
		c.JSON(http.StatusInternalServerError, gin.H{"error": "execution failed"})
		return
	}

	c.JSON(http.StatusOK, ScriptResponse{
		ExitCode:        result.ExitCode,
		Stdout:          result.Stdout,
		Stderr:          result.Stderr,
		ExecutionTimeMs: result.ExecutionTimeMs,
		TimedOut:        result.TimedOut,
	})
}
