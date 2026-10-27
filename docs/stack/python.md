# Python, uv, Ruff and Pyright (the engine's toolchain)

The engine is Python 3.14, managed end to end by [uv](https://docs.astral.sh/uv/): uv installs
Python itself, creates `engine/.venv`, locks every package in `engine/uv.lock`, and runs the tools.
[Ruff](https://docs.astral.sh/ruff/) lints and formats; [Pyright](https://microsoft.github.io/pyright/)
checks types in strict mode.

## Files

| File | What it holds |
| --- | --- |
| `engine/pyproject.toml` | The package, its dependencies, and settings for uv, Ruff, Pyright and pytest |
| `engine/uv.lock` | Exact versions of everything; committed |
| `engine/.python-version` | `3.14` |
| `engine/src/maku/` | The package (the `src` layout keeps tests honest: they import the installed package) |
| `engine/tests/` | pytest tests |

## uv

```powershell
cd engine
uv sync                 # create or update .venv to match uv.lock exactly
uv run <command>        # run anything inside the environment (pytest, maku, pyinstaller…)
uv add httpx2           # add a dependency (uv add --dev for tools)
uv lock --upgrade       # move every package to its latest version
uv python install 3.14  # fetch the newest 3.14 patch release
```

`[tool.uv]` pins `python-preference = "only-managed"`: every machine uses uv's own Python build,
never whatever is installed system-wide, so development, CI and the installer match.
`required-version` stops an old uv from writing the lockfile.

The package is built with `uv_build` (uv's build backend) and installs a `maku` command
(`[project.scripts]`), which is what `uv run maku …` and the shell call in development.

## Ruff

`uv run ruff format` formats (100 columns); `uv run ruff check` lints with the rule sets listed in
`pyproject.toml`: pyflakes and pycodestyle, import order, naming, modern syntax, likely bugs,
pathlib, returns, security (bandit) and pytest style. Tests may use `assert`, test tokens and
subprocesses. `uv run ruff check --fix` applies safe fixes.

Suppress a finding only on its line, with the reason: `# noqa: S603 — fixed command, no user input`.

## Pyright

`uv run pyright` checks `src` and `tests` in **strict** mode: every function is annotated, nothing
is silently `Any`. When a library's types are incomplete, narrow once at the boundary (see
`_paths` in `api/common.py`) instead of spreading ignores.

## Python 3.14 notes

- Annotations are lazily evaluated, so a class can name itself in its own annotations without
  quotes (`def default(cls) -> DataPaths`).
- Use `datetime.UTC`, `pathlib`, `match`, and parenthesised context managers freely.
- Every dependency Maku needs, including ONNX Runtime with DirectML for the speech models, has
  Python 3.14 wheels.

## Upgrading

`uv self update`, `uv python install 3.14`, `uv lock --upgrade`, raise the minimums in
`pyproject.toml` to match, then run every check. A new Python minor (3.15) needs all dependencies,
especially ONNX Runtime and PyInstaller, to support it first.
