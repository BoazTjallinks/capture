package limiter

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

func TestLimiterRejectsWhenFull(t *testing.T) {
	l := New(1, 1) // one in-flight, one queued
	ctx := context.Background()

	if err := l.Acquire(ctx); err != nil {
		t.Fatalf("first acquire should succeed: %v", err)
	}

	// Second should queue but not be rejected — start it in a goroutine
	// so it doesn't block the test forever.
	var wg sync.WaitGroup
	wg.Add(1)
	queueDone := make(chan struct{})
	go func() {
		defer wg.Done()
		if err := l.Acquire(ctx); err != nil {
			t.Errorf("second acquire should queue: %v", err)
		}
		close(queueDone)
		l.Release()
	}()

	// Give the goroutine a moment to enter the queue.
	time.Sleep(20 * time.Millisecond)

	// Third should be rejected.
	if err := l.Acquire(ctx); !errors.Is(err, ErrCapacityExceeded) {
		t.Fatalf("expected ErrCapacityExceeded, got %v", err)
	}

	// Release first; queued goroutine should now run.
	l.Release()
	<-queueDone
	wg.Wait()
}

func TestLimiterContextCancel(t *testing.T) {
	l := New(1, 5)
	ctx := context.Background()
	if err := l.Acquire(ctx); err != nil {
		t.Fatalf("first acquire: %v", err)
	}
	cancelCtx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(20 * time.Millisecond)
		cancel()
	}()
	if err := l.Acquire(cancelCtx); !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context cancellation, got %v", err)
	}
	l.Release()
}
