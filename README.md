# neatsprint-lib

Shared runtime library for NeatSprint FastAPI services.

| Module | Provides |
| :--- | :--- |
| `settings` | `ServiceSettings` (12-factor, `.env` aware) |
| `logging` | JSON log formatter and `configure_logging` |
| `errors` | `ApiError`, RFC 7807 handlers, validation mapping |
| `context` | Request/tenant/user context vars + correlation-id middleware |
| `api` | `/healthz`, `/readyz`, `/metrics`, request metrics middleware |
| `db` | Async engine/session factory, base model mixins, tenant-scoped repository |
| `ids` | UUIDv7 helpers |

## Install

Services consume this library as a pinned git dependency:

```toml
[dependencies]
neatsprint-lib = { git = "https://github.com/neatsprint/neatsprint-lib", tag = "v0.1.0" }
```

## Develop

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```

## Conventions

- No business logic from any specific domain; this package is generic infrastructure.
- Never import FastAPI routers from services.
- Every DB model mixin must keep the tenant filter explicit.
- Backwards-incompatible changes require a SemVer bump and a changelog entry.
