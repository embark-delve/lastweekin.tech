# Agent Workflow Guidelines

- Use the [uv](https://docs.astral.sh/uv/) toolchain for Python dependency and environment management. Prefer commands such as `uv init`, `uv venv --python 3.12`, `uv add`, `uv lock`, and `uv run` instead of Poetry.
- Format and lint Python code with Ruff (both `ruff format` and `ruff check`). Do not use Black or Flake8.
- Run security and quality tooling via pre-commit, which is configured to include Ruff, Bandit, Codespell, Prettier, and Markdownlint. Install hooks with `uv run pre-commit install` and execute them with `uv run pre-commit run --all-files` when touching relevant files.
- Favor modern static analysis such as `mypy` for type checking and `bandit` for security scanning. Avoid introducing redundant or legacy linters.
- Keep documentation and configuration files formatted with Prettier or Markdownlint as applicable.
- When introducing new dependencies, update `pyproject.toml` and run `uv lock` to maintain a consistent lockfile.
