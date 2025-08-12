# AI agent instructions for hass-nabucasa

This file provides guidance to AI agents (Claude Code, GitHub Copilot, etc.) when working with code in this repository.

## Meta instructions

Important: Keep this file accurate and up to date. Update it immediately when (1) users give new instructions, (2) you find contradictions, or (3) new patterns or standards emerge. Treat this maintenance as a blocking, highest‑priority task that doesn’t need an explicit prompt.

Note: This file is exempt from the “no new docs” rule below. Proactively edit and maintain this file as part of your duties.

## Development commands

### Testing
- Use `scripts/test` to run the full suite (pytest). Defaults come from `pyproject.toml` (socket disabled, 127.0.0.1 allowed, timeout=5).
- Run a module: `python -m pytest tests/test_<module>.py`.
- Run a single test: `python -m pytest tests/test_<module>.py::test_function`.
- Update snapshots when needed: `scripts/snapshot-update`.
- Local iteration tips (optional): add `-x` to stop on first failure; `--no-header --no-summary --tb=short` for compact output.

Important: All tests must pass. Partial success isn’t acceptable.
- Fix every test failure before you consider the task complete.
- If any test fails, the testing phase fails.
- Don’t ignore or skip failing tests — they indicate bugs that must be resolved.
- Run the full test suite after changes to ensure nothing breaks.
- Test failures block merges.

### Code quality
- `scripts/lint` — Run pre-commit hooks (ruff, mypy, codespell, etc.).
- `ruff check` — Run ruff linting.
- `mypy hass_nabucasa` — Run type checking.

### Environment
- Python: >= 3.13 (see `pyproject.toml`). Ruff target: `py313`.
- Before pushing, run `scripts/lint` and `scripts/test` locally.

### Voice data updates
- `python -m scripts.update_voice_data` — Update voice data from Azure (requires Azure TTS token).

## Architecture overview

### Core components

**Cloud class (`hass_nabucasa/__init__.py`)**
- Main orchestrator for cloud functionality.
- Handles authentication state, subscription validation, and component lifecycle.
- Manages tokens (id_token, access_token, refresh_token) and user authentication.
- Initializes sub-components: `iot`, `account`, `accounts`, `alexa_api`, `auth`, `cloudhooks`, `files`, `google_report_state`, `ice_servers`, `instance`, `payments`, `remote`, `voice`, `voice_api`.

**CloudClient interface (`hass_nabucasa/client.py`)**
- Abstract base class that Home Assistant implements.
- Provides platform-specific functionality (file system, event loop, web session).
- Handles client-specific callbacks and cleanup operations.

**CloudIoT (`hass_nabucasa/iot.py`)**
- WebSocket-based communication with Nabu Casa cloud services.
- Handles message routing, heartbeats, and connection management.
- Implements request–response patterns for cloud API calls.

### API components

All API components extend `ApiBase` and provide specific cloud service integrations:
- AccountApi — User account service availability/status.
- AlexaApi — Amazon Alexa integration and access tokens.
- PaymentsApi — Payment processing and subscription management.
- VoiceApi — Voice processing and TTS services.
- InstanceApi — Instance connection and management.
- FilesApi — Cloud file management and backup storage.
- AccountsApi — Accounts backend utility APIs (for example, DNS CNAME resolution).

### Key services

**Authentication (`hass_nabucasa/auth.py`)**
- AWS Cognito integration for user authentication.
- Token refresh and validation.
- MFA/TOTP support.

**Remote UI (`hass_nabucasa/remote.py`)**
- ACME certificate management for secure remote access.
- SniTun tunnel integration for remote connectivity.

**Cloudhooks (`hass_nabucasa/cloudhooks.py`)**
- Webhook management for cloud-to-local communication.
- Dynamic webhook URL generation and routing.

### Configuration and constants

**Environment configuration (`hass_nabucasa/const.py`)**
- Production vs. development server endpoints.
- AWS Cognito configuration (client ID, user pool, region).
- Default timeout values and connection states.

**Mode support**
- `Cloud(mode)` accepts `"production"` or `"development"`.
- Production: Uses defaults from `DEFAULT_SERVERS` and `DEFAULT_VALUES`.
- Development: Provide servers/values via the `Cloud(...)` constructor for tests/dev.

## Development notes

### Testing strategy
- Unit tests for all major components in `tests/`.
- Mocking for external services (AWS, cloud APIs).
- Snapshot testing for voice data using syrupy.
- Async test support with pytest-aiohttp.
- Network calls are disabled by default (`pytest-socket --disable-socket` with 127.0.0.1 allowed).
- Use freezegun to freeze time globally to 2018‑09‑17.

**Time handling in tests**
- Global `freeze_time_fixture` in `tests/conftest.py` freezes time to "2018-09-17 12:00:00" with `tick=True`.
- The `mock_timing` fixture (used in remote tests) provides targeted patches for sleep/random/midnight. Use it where appropriate instead of changing global behavior.
- Don’t modify the global time freeze. Changes affect the whole suite.

### Code style
- Strict typing with mypy (type all functions).
- Ruff for linting and formatting (line length 88).
- Docstrings follow PEP 257 conventions.
- Pre-commit hooks enforce code quality.
- Import organization: Keep all imports at the top level of modules (never inside functions or methods).
- Comments policy: Don’t add unnecessary inline comments — prefer clear names and structure.
- Async I/O: Use `cloud.run_executor` for blocking file I/O or CPU‑heavy work.

### Error handling
- Custom exception hierarchy extending `CloudError`.
- Specific error types for different failure modes (auth, network, subscription).
- Automatic retry logic for transient failures.

### Logging standards
- Use `_LOGGER = logging.getLogger(__name__)` in modules.
- Exception: `iot_base.py` uses `self._logger = logging.getLogger(self.package_name)` for instance-based logging.
- Message guidance:
  - Use “Unexpected error …” for exception-level logging.
  - Prefer descriptive, consistent phrasing (for example, “Unable to connect due to …”).
  - Include context in error messages (for example, “Unexpected error handling message: %s”).
  - Use present tense and active voice.
- Severity levels:
  - `debug()` — Development/troubleshooting info.
  - `info()` — Normal operation events.
  - `warning()` — Recoverable issues that should be noted.
  - `error()` — Non‑recoverable errors requiring attention.
  - `exception()` — Errors with full stack traces for debugging.

### Subscription management
- Automatic reconnection handler for expired subscriptions.
- Graceful degradation when a subscription is invalid.
- Repair issue creation for user notification.

## File creation guidelines

Important: File creation policy
- Do only what the task asks. Don’t add extras.
- Don’t create files unless they’re necessary to achieve the goal.
- Always prefer editing an existing file to creating a new one.
- Don’t proactively create documentation files (`*.md`) or README files. Create documentation only if the user explicitly asks.
- Exception: Proactively maintain this `.github/copilot-instructions.md` file (see “Meta instructions”).

## Security guidelines

Important: Security policy
- Assist with defensive security tasks only.
- Refuse to create, modify, or improve code that could be used maliciously.
- Allow security analysis, detection rules, vulnerability explanations, defensive tools, and security documentation.
- Always follow security best practices.
- Don’t introduce code that exposes or logs secrets or keys.
- Don’t commit secrets or keys to the repository.

### Security baselines (current state)
- Don’t log secrets or tokens. Favor contextual messages without sensitive data.
- JWT decoding for convenience uses signature verification disabled (see `Cloud._decode_claims` and `utils.expiration_from_token`). Don’t rely on unverified claims for security decisions.
- TLS contexts follow a modern cipher suite selection (`utils.server_context_modern`), with legacy protocol versions disabled.
- ACME artifacts and user info are stored with `0o600` permissions, and critical writes use atomic writes (see `acme.py` and `hass_nabucasa/__init__.py`).
- ACME RSA key sizes currently default to 2048 bits (`acme.py`). If you change sizes, update tests and validate performance.

### Security testing expectations
- Validate security-related code paths with automated tests where feasible.
- Prefer explicit failure modes and clear error messages without leaking sensitive details.
