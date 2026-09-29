# Contributing to FinSight

Thank you for your interest in contributing! FinSight is an open project and welcomes improvements, bug reports, and feature ideas.

---

## Getting Started

1. **Fork** the repository and clone your fork locally.
2. Create a virtual environment and install dependencies:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   # source .venv/bin/activate     # macOS / Linux
   pip install -r requirements.txt
   ```
3. Copy the example environment file and initialise the database:
   ```powershell
   copy .env.example .env
   flask init-db
   ```
4. Run the test suite to confirm everything is green before making changes:
   ```powershell
   pytest
   ```

---

## Development Workflow

### Branching
- `main` — stable, always passing CI.
- Feature branches: `feature/<short-description>` (e.g. `feature/pdf-ocr-support`).
- Bug-fix branches: `fix/<short-description>`.

### Making Changes
- Keep commits focused and atomic.
- Follow the existing code style (PEP 8, 4-space indentation, type hints where practical).
- Update or add tests for any changed behaviour — the test suite must remain green.
- Update `README.md` if your change adds or modifies a feature, endpoint, or configuration option.

### Running Tests
```powershell
# Full suite (no external services required — uses the fake LLM gateway)
pytest

# With coverage
pytest --cov=app --cov-report=term-missing
```

---

## Submitting a Pull Request

1. Push your branch to your fork.
2. Open a Pull Request against `main` on the upstream repository.
3. Fill in the PR template:
   - **What does this PR do?** — a clear, concise description.
   - **How was it tested?** — mention relevant test files or manual steps.
   - **Breaking changes?** — list any API or configuration changes.
4. A maintainer will review and may request changes before merging.

---

## Reporting Issues

Open a GitHub Issue and include:
- A clear title and description of the problem.
- Steps to reproduce.
- Expected vs. actual behaviour.
- Python version, OS, and relevant environment variables (redact secrets).

---

## Code of Conduct

Be respectful. We follow the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) Code of Conduct.

---

## License

By contributing, you agree that your contributions will be licensed under the [Apache 2.0 License](LICENSE).
