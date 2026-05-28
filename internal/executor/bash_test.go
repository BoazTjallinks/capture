//go:build !windows

package executor

import (
	"context"
	"os/exec"
	"runtime"
	"strings"
	"testing"
)

func TestBashExecutorExitCodes(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("bash test skipped on Windows")
	}
	if _, err := exec.LookPath("bash"); err != nil {
		t.Skip("bash not available in PATH")
	}
	b := NewBashExecutor()

	cases := []struct {
		name     string
		body     string
		expected int
	}{
		{"success", "echo hello && exit 0", 0},
		{"failure", "exit 7", 7},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			res, err := b.Execute(context.Background(), Request{
				Runtime:   RuntimeBash,
				Body:      tc.body,
				TimeoutMs: 5000,
			})
			if err != nil {
				t.Fatalf("execute: %v", err)
			}
			if res.ExitCode != tc.expected {
				t.Fatalf("expected exit %d, got %d (stderr=%q)", tc.expected, res.ExitCode, res.Stderr)
			}
		})
	}
}

func TestBashExecutorParametersInjected(t *testing.T) {
	if _, err := exec.LookPath("bash"); err != nil {
		t.Skip("bash not available in PATH")
	}
	b := NewBashExecutor()
	res, err := b.Execute(context.Background(), Request{
		Runtime:    RuntimeBash,
		Body:       "echo $SCRIPT_PARAM_FOO",
		TimeoutMs:  5000,
		Parameters: map[string]string{"FOO": "BAR"},
	})
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if !strings.Contains(res.Stdout, "BAR") {
		t.Fatalf("expected stdout to contain BAR, got %q", res.Stdout)
	}
}

func TestBashExecutorTimeout(t *testing.T) {
	if _, err := exec.LookPath("bash"); err != nil {
		t.Skip("bash not available in PATH")
	}
	b := NewBashExecutor()
	res, err := b.Execute(context.Background(), Request{
		Runtime:   RuntimeBash,
		Body:      "sleep 5",
		TimeoutMs: 100,
	})
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if !res.TimedOut {
		t.Fatalf("expected timed_out=true")
	}
}
