package runtime

import "testing"

func TestRegistryResolvesTrustedPythonRuntime(t *testing.T) {
	config, err := NewRegistry().Resolve(Python311V1)
	if err != nil {
		t.Fatalf("Resolve() error = %v", err)
	}
	if config.ID != Python311V1 || config.Language != "python" || config.Image == "" {
		t.Fatalf("config = %#v, want trusted Python configuration", config)
	}
	if len(config.Command) != 2 || config.Command[0] != "python3" || config.Command[1] != "-c" {
		t.Fatalf("command = %#v, want fixed python3 -c command", config.Command)
	}
	if !config.SupportsIOProtocol("json-stdio-v1") {
		t.Fatal("runtime must support json-stdio-v1")
	}
}

func TestRegistryRejectsUnknownRuntime(t *testing.T) {
	if _, err := NewRegistry().Resolve("rust-1.80-v1"); err != ErrUnknownRuntime {
		t.Fatalf("Resolve() error = %v, want %v", err, ErrUnknownRuntime)
	}
}

func TestRegistryResolvesTrustedCppGcc14Cpp20Runtime(t *testing.T) {
	config, err := NewRegistry().Resolve(CppGcc14Cpp20V1)
	if err != nil {
		t.Fatalf("Resolve() error = %v", err)
	}
	const approvedImage = "m.daocloud.io/docker.io/library/gcc@sha256:cb57ac6c7917425c057c736fe3a240df25bce310418d61cd223bc8e411364876"
	if config.Language != "cpp" || config.Toolchain != "gcc-14/cpp20" || config.Image != approvedImage {
		t.Fatalf("config = %#v, want fixed GCC 14/C++20 runtime", config)
	}
	if config.CompileWallTimeout.Milliseconds() != 15_000 || config.CompileMemory != "512m" || config.CompiledProgram != "/arena/out/program" {
		t.Fatalf("compile configuration = %#v, want fixed compile budget and artifact path", config)
	}
	wantCommand := []string{"g++", "-std=c++20", "-O2", "-pipe", "-o", "/arena/out/program", "/arena/out/main.cpp"}
	if len(config.CompileCommand) != len(wantCommand) {
		t.Fatalf("compile command = %#v, want %#v", config.CompileCommand, wantCommand)
	}
	for index := range wantCommand {
		if config.CompileCommand[index] != wantCommand[index] {
			t.Fatalf("compile command[%d] = %q, want %q", index, config.CompileCommand[index], wantCommand[index])
		}
	}
}
