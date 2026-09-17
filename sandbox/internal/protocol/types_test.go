package protocol

import (
	"strings"
	"testing"
)

func TestValidateRequestRejectsUnknownProtocol(t *testing.T) {
	request := ExecuteRequest{
		Code:            "print('ok')",
		StdinInput:      "{}",
		ProtocolVersion: "unsupported-v1",
	}

	if err := request.Validate(); err == nil {
		t.Fatal("Validate() error = nil, want an unsupported protocol error")
	}
}

func TestValidateRequestUsesUTF8ByteLimits(t *testing.T) {
	request := ExecuteRequest{
		Code:            strings.Repeat("界", MaxCodeBytes/3+1),
		StdinInput:      "{}",
		ProtocolVersion: JSONStdioV1,
	}

	if err := request.Validate(); err == nil {
		t.Fatal("Validate() error = nil, want code byte limit error")
	}
}
