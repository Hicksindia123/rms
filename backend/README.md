# RMS backend

FastAPI + Pydantic v2 service. Layering: `router -> service -> repository` (see `../CLAUDE.md`).

```bash
uv sync                                              # install deps (Python 3.12)
uv run uvicorn app.main:app --reload --port 8000     # run API
uv run pytest -q                                     # tests
uv run ruff check . && uv run mypy app               # lint + types
```

Health check: `GET http://localhost:8000/api/v1/health`.

Copy `.env.example` to `.env` and fill in values (see `../docs/SETUP.md`). Never commit `.env`.
