package config

import (
	"log"
	"strings"
)

type Config struct {
	Port      string
	APISecret string

	// Script execution feature flag and configuration. When
	// ScriptExecutionEnabled is false (default) the /api/v1/script
	// endpoint is not registered, preserving backward compatibility
	// with existing Capture deployments.
	ScriptExecutionEnabled bool
	AllowedRuntimes        []string
}

var defaultPort = "59232"
var defaultAllowedRuntimes = []string{"bash"}

func NewConfig(port string, apiSecret string) *Config {
	// Set default port if not provided
	if port == "" {
		port = defaultPort
	}

	// Print error message if API_SECRET is not provided
	if apiSecret == "" {
		log.Fatalln("API_SECRET environment variable is required for security purposes. Please set it before starting the server.")
	}

	return &Config{
		Port:                   port,
		APISecret:              apiSecret,
		ScriptExecutionEnabled: false,
		AllowedRuntimes:        defaultAllowedRuntimes,
	}
}

// WithScriptExecution lets the caller enable script execution and
// override the allowed runtime list. allowed is expected to be a
// comma-separated string like "bash,python".
func (c *Config) WithScriptExecution(enabled bool, allowed string) *Config {
	c.ScriptExecutionEnabled = enabled
	if allowed != "" {
		parts := strings.Split(allowed, ",")
		cleaned := make([]string, 0, len(parts))
		for _, p := range parts {
			p = strings.TrimSpace(strings.ToLower(p))
			if p != "" {
				cleaned = append(cleaned, p)
			}
		}
		if len(cleaned) > 0 {
			c.AllowedRuntimes = cleaned
		}
	}
	return c
}

func Default() *Config {
	return &Config{
		Port:                   defaultPort,
		APISecret:              "",
		ScriptExecutionEnabled: false,
		AllowedRuntimes:        defaultAllowedRuntimes,
	}
}
