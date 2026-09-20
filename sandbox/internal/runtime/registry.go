package runtime

import (
	"errors"
	"time"
)

const (
	Python311V1     = "python-3.11-v1"
	CppGcc14Cpp20V1 = "cpp-gcc-14-cpp20-v1"
)

var ErrUnknownRuntime = errors.New("unknown runtime")

type Config struct {
	ID                 string
	Language           string
	Toolchain          string
	Image              string
	Command            []string
	IOProtocols        map[string]struct{}
	WallTimeout        time.Duration
	NetworkMode        string
	ReadOnly           bool
	Tmpfs              string
	User               string
	CPUs               string
	Memory             string
	MemorySwap         string
	PIDsLimit          string
	CapDrop            string
	NoNewPrivileges    bool
	MaxSourceBytes     int
	MaxInputBytes      int
	MaxOutputBytes     int
	CompileWallTimeout time.Duration
	CompileTmpfs       string
	CompileMemory      string
	CompileMemorySwap  string
	CompileCommand     []string
	CompiledProgram    string
}

func (config Config) SupportsIOProtocol(protocol string) bool {
	_, ok := config.IOProtocols[protocol]
	return ok
}

type Registry struct {
	configs map[string]Config
}

func NewRegistry() *Registry {
	return &Registry{configs: map[string]Config{
		Python311V1: {
			ID:              Python311V1,
			Language:        "python",
			Toolchain:       "python-3.11",
			Image:           "m.daocloud.io/docker.io/library/python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534",
			Command:         []string{"python3", "-c"},
			IOProtocols:     map[string]struct{}{"json-stdio-v1": {}},
			WallTimeout:     5 * time.Second,
			NetworkMode:     "none",
			ReadOnly:        true,
			Tmpfs:           "/tmp:size=64m,noexec",
			User:            "65534:65534",
			CPUs:            "1",
			Memory:          "128m",
			MemorySwap:      "128m",
			PIDsLimit:       "32",
			CapDrop:         "ALL",
			NoNewPrivileges: true,
			MaxSourceBytes:  64 * 1024,
			MaxInputBytes:   64 * 1024,
			MaxOutputBytes:  64 * 1024,
		},
		CppGcc14Cpp20V1: {
			ID:                 CppGcc14Cpp20V1,
			Language:           "cpp",
			Toolchain:          "gcc-14/cpp20",
			Image:              "m.daocloud.io/docker.io/library/gcc@sha256:cb57ac6c7917425c057c736fe3a240df25bce310418d61cd223bc8e411364876",
			IOProtocols:        map[string]struct{}{"json-stdio-v1": {}},
			WallTimeout:        5 * time.Second,
			CompileWallTimeout: 15 * time.Second,
			NetworkMode:        "none",
			ReadOnly:           true,
			Tmpfs:              "/tmp:size=64m,noexec",
			CompileTmpfs:       "/tmp:size=64m,exec",
			User:               "65534:65534",
			CPUs:               "1",
			Memory:             "128m",
			MemorySwap:         "128m",
			CompileMemory:      "512m",
			CompileMemorySwap:  "512m",
			PIDsLimit:          "32",
			CapDrop:            "ALL",
			NoNewPrivileges:    true,
			MaxSourceBytes:     64 * 1024,
			MaxInputBytes:      64 * 1024,
			MaxOutputBytes:     64 * 1024,
			CompileCommand:     []string{"g++", "-std=c++20", "-O2", "-pipe", "-o", "/arena/out/program", "/arena/out/main.cpp"},
			CompiledProgram:    "/arena/out/program",
		},
	}}
}

func (registry *Registry) Resolve(runtimeID string) (Config, error) {
	config, ok := registry.configs[runtimeID]
	if !ok {
		return Config{}, ErrUnknownRuntime
	}
	config.Command = append([]string(nil), config.Command...)
	config.CompileCommand = append([]string(nil), config.CompileCommand...)
	config.IOProtocols = cloneProtocols(config.IOProtocols)
	return config, nil
}

func (registry *Registry) ResolveImage(image string) (Config, error) {
	for _, config := range registry.configs {
		if config.Image == image {
			config.Command = append([]string(nil), config.Command...)
			config.CompileCommand = append([]string(nil), config.CompileCommand...)
			config.IOProtocols = cloneProtocols(config.IOProtocols)
			return config, nil
		}
	}
	return Config{}, ErrUnknownRuntime
}

func cloneProtocols(protocols map[string]struct{}) map[string]struct{} {
	cloned := make(map[string]struct{}, len(protocols))
	for protocol := range protocols {
		cloned[protocol] = struct{}{}
	}
	return cloned
}
