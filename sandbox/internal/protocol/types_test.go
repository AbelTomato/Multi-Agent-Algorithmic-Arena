package protocol

import (
	"strings"
	"testing"
)

func TestValidateRequestLeavesRuntimeIOProtocolSupportToRegistry(t *testing.T) {
	request := ExecuteRequest{
		APIVersion: ExecutionAPIV2,
		RuntimeID:  "python-3.11-v1",
		Source:     "print('ok')",
		StdinInput: "{}",
		IOProtocol: "unsupported-v1",
	}

	if err := request.Validate(); err != nil {
		t.Fatalf("Validate() error = %v, want structural validation to pass", err)
	}
}

func TestDecodeRequestUsesUTF8ByteLimits(t *testing.T) {
	request := ExecuteRequest{
		APIVersion: ExecutionAPIV2,
		RuntimeID:  "python-3.11-v1",
		Source:     strings.Repeat("界", MaxSourceBytes/3+1),
		StdinInput: "{}",
		IOProtocol: JSONStdioV1,
	}

	if err := request.Validate(); err == nil {
		t.Fatal("Validate() error = nil, want source byte limit error")
	}
}

func TestDecodeRequestRejectsLegacyFields(t *testing.T) {
	if _, err := DecodeExecuteRequest([]byte(`{"code":"print(1)","stdin_input":"{}","protocol_version":"json-stdio-v1"}`)); err == nil {
		t.Fatal("DecodeExecuteRequest() error = nil, want legacy request rejection")
	}
}
