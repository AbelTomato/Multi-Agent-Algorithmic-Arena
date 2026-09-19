package main

import "testing"

func TestListenAddressDefaultsToLoopback(t *testing.T) {
	t.Setenv(listenAddressEnvironmentVariable, "")

	address, err := listenAddress()
	if err != nil {
		t.Fatalf("listenAddress() error = %v", err)
	}
	if address != defaultListenAddress {
		t.Fatalf("listenAddress() = %q, want %q", address, defaultListenAddress)
	}
}

func TestListenAddressAcceptsLoopbackAndPrivateIPv4(t *testing.T) {
	for _, address := range []string{"127.0.0.1:8001", "172.30.0.1:8001"} {
		t.Run(address, func(t *testing.T) {
			t.Setenv(listenAddressEnvironmentVariable, address)

			actual, err := listenAddress()
			if err != nil {
				t.Fatalf("listenAddress() error = %v", err)
			}
			if actual != address {
				t.Fatalf("listenAddress() = %q, want %q", actual, address)
			}
		})
	}
}

func TestListenAddressRejectsPublicAndMalformedAddresses(t *testing.T) {
	for _, address := range []string{
		"0.0.0.0:8001",
		"47.119.120.86:8001",
		"172.30.0.1:9000",
		"localhost:8001",
		"172.30.0.1",
	} {
		t.Run(address, func(t *testing.T) {
			t.Setenv(listenAddressEnvironmentVariable, address)
			if _, err := listenAddress(); err == nil {
				t.Fatal("listenAddress() error = nil, want rejection")
			}
		})
	}
}
