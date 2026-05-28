// Package limiter implements a simple bounded-concurrency limiter with
// a fixed-size queue. It returns ErrCapacityExceeded immediately when
// the queue is full instead of blocking forever, so the HTTP handler
// can reply with 429 to overloaded clients.
package limiter

import (
	"context"
	"errors"
)

// ErrCapacityExceeded is returned by Acquire when the queue is full.
var ErrCapacityExceeded = errors.New("execution queue is full")

// Limiter bounds the number of concurrently running tasks. The
// in-flight permits semaphore + a queue token semaphore together cap
// the total number of waiting + running tasks at MaxQueue.
type Limiter struct {
	inflight chan struct{}
	queue    chan struct{}
}

// New creates a Limiter with maxConcurrent simultaneous executions
// and maxQueue additional queued executions. Behaviour:
//   - <= maxConcurrent in-flight: Acquire returns immediately.
//   - maxConcurrent in-flight + queue space: Acquire blocks until a slot
//     frees, then returns nil.
//   - queue full: Acquire returns ErrCapacityExceeded.
func New(maxConcurrent, maxQueue int) *Limiter {
	if maxConcurrent <= 0 {
		maxConcurrent = 1
	}
	if maxQueue < 0 {
		maxQueue = 0
	}
	return &Limiter{
		inflight: make(chan struct{}, maxConcurrent),
		queue:    make(chan struct{}, maxConcurrent+maxQueue),
	}
}

// Acquire grabs a permit. The caller must call Release when finished.
func (l *Limiter) Acquire(ctx context.Context) error {
	// Try to reserve a queue slot (non-blocking).
	select {
	case l.queue <- struct{}{}:
		// queued / running slot reserved
	default:
		return ErrCapacityExceeded
	}

	// Wait for an in-flight permit.
	select {
	case l.inflight <- struct{}{}:
		return nil
	case <-ctx.Done():
		// Release the queue token we reserved.
		<-l.queue
		return ctx.Err()
	}
}

// Release returns one in-flight permit and one queue token.
func (l *Limiter) Release() {
	<-l.inflight
	<-l.queue
}
