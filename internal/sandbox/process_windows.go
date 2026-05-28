//go:build windows

package sandbox

import "os/exec"

// startProcessGroup is a no-op on Windows; we rely on CommandContext
// killing the child when the context is cancelled.
func startProcessGroup(cmd *exec.Cmd) {
	_ = cmd
}

// killProcessGroup attempts to terminate the child process.
func killProcessGroup(cmd *exec.Cmd) {
	if cmd.Process == nil {
		return
	}
	_ = cmd.Process.Kill()
}
