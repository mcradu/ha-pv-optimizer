# Changelog

## 0.1.2

- Request an explicit Supervisor API token in addition to Core API proxy access.
- Accept the legacy `HASSIO_TOKEN` environment name as a compatibility fallback.
- Report which token source is available without exposing token contents.

## 0.1.1

- Expose Supervisor API diagnostics without exposing the token.
- Log connection failures once per distinct error.
- Show entity-specific errors and runtime diagnostics in the Web UI.

## 0.1.0

- Add Home Assistant app repository metadata.
- Add read-only Supervisor Core API client.
- Add V5.8.2-compatible shadow calculation engine.
- Add persistent cycle state and restart recovery metadata.
- Add responsive Ingress Web UI with simulated controls.
- Add health, status, decision, configuration, and log APIs.
- Add unit tests and secret-safe diagnostics.
