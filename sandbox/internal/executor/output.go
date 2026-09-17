package executor

import "sync"

type OutputCollector struct {
	mu       sync.Mutex
	limit    int
	stdout   []byte
	stderr   []byte
	total    int
	exceeded bool
}

func NewOutputCollector(limit int) *OutputCollector {
	return &OutputCollector{limit: limit}
}

func (collector *OutputCollector) WriteStdout(data []byte) bool {
	return collector.write(&collector.stdout, data)
}

func (collector *OutputCollector) WriteStderr(data []byte) bool {
	return collector.write(&collector.stderr, data)
}

func (collector *OutputCollector) write(destination *[]byte, data []byte) bool {
	collector.mu.Lock()
	defer collector.mu.Unlock()
	remaining := collector.limit - collector.total
	exceedsLimit := len(data) > remaining
	if remaining > 0 {
		if exceedsLimit {
			data = data[:remaining]
		}
		*destination = append(*destination, data...)
		collector.total += len(data)
	}
	if exceedsLimit {
		collector.exceeded = true
	}
	return collector.exceeded
}

func (collector *OutputCollector) TotalBytes() int {
	collector.mu.Lock()
	defer collector.mu.Unlock()
	return collector.total
}

func (collector *OutputCollector) Exceeded() bool {
	collector.mu.Lock()
	defer collector.mu.Unlock()
	return collector.exceeded
}

func (collector *OutputCollector) Stdout() string {
	collector.mu.Lock()
	defer collector.mu.Unlock()
	return string(collector.stdout)
}

func (collector *OutputCollector) Stderr() string {
	collector.mu.Lock()
	defer collector.mu.Unlock()
	return string(collector.stderr)
}
