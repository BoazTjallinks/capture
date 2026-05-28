//go:build !windows

package sandbox

import (
	"os/exec"
	"syscall"
)

// startProcessGroup configures the child to run in a new process group
// so we can kill any sub-processes it spawns when we timeout.
func startProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setpgid: true,
	}
}

// killProcessGroup sends SIGKILL to the entire process group. Best effort.
func killProcessGroup(cmd *exec.Cmd) {
	if cmd.Process == nil {
		return
	}
	pgid, err := syscall.Getpgid(cmd.Process.Pid)
	if err == nil {
		_ = syscall.Kill(-pgid, syscall.SIGKILL)
	} else {
		_ = cmd.Process.Kill()
	}
}
