# Testing Guide for Orion

This document explains how unit tests are triggered and how to run tests locally and in CI/CD.

## How Tests Are Triggered on Git Push

### GitHub Actions (Automated CI/CD)

When you push code to GitHub, tests are **automatically triggered** by GitHub Actions:

1. **On Every Push** to `main` or `develop` branches
2. **On Every Pull Request** targeting `main` or `develop`

The workflow runs:
- ✅ Unit tests on Python 3.11 and 3.12
- ✅ Code coverage analysis
- ✅ Linting (Black, Ruff)
- ✅ Type checking (mypy)

**Configuration**: [.github/workflows/test.yml](.github/workflows/test.yml)

### Viewing Test Results

After pushing to GitHub:
1. Go to your repository on GitHub
2. Click the "Actions" tab
3. Find your recent push/PR
4. View test results, logs, and coverage reports

## Running Tests Locally

### Quick Commands (Using Makefile)

```bash
# Run all tests
make test

# Run tests with coverage HTML report
make test-cov

# Run only unit tests
make test-unit

# Run only integration tests (when available)
make test-integration

# Run all CI checks (format, lint, type-check, test)
make ci
```

### Using Poetry Directly

```bash
# Run all tests
poetry run pytest

# Run with verbose output
poetry run pytest -v

# Run specific test file
poetry run pytest tests/unit/test_config.py

# Run specific test
poetry run pytest tests/unit/test_config.py::TestDataProviderConfig::test_from_env

# Run with coverage
poetry run pytest --cov=orion --cov-report=html --cov-report=term-missing

# Run only unit tests
poetry run pytest tests/unit/

# Run tests matching a pattern
poetry run pytest -k "test_config"

# Run tests with specific markers
poetry run pytest -m "not integration"  # Skip integration tests
```

## Pre-commit Hooks (Test Before You Commit)

Install pre-commit hooks to automatically run tests **before each git commit**:

### Installation

```bash
# Using Makefile
make pre-commit

# Or manually
pip install pre-commit
pre-commit install
```

### What Happens on Commit

When you run `git commit`, the following checks run automatically:

1. **Code Formatting** - Black formats your code
2. **Linting** - Ruff checks for code quality issues
3. **Type Checking** - mypy validates type hints
4. **Unit Tests** - All unit tests must pass

If any check fails, the commit is blocked and you see the errors.

### Bypassing Pre-commit (Not Recommended)

```bash
git commit --no-verify -m "message"
```

## Test Structure

```
tests/
├── test_project_setup.py      # Basic package import tests
├── unit/                       # Unit tests (fast, isolated)
│   ├── test_config.py         # Configuration tests (18 tests)
│   └── test_logging.py        # Logging tests (12 tests)
├── integration/                # Integration tests (slower, with real APIs)
│   └── (coming in Phase 2+)
└── fixtures/                   # Shared test data
    └── (coming in Phase 2+)
```

## Current Test Coverage

**Phase 1 Tests** (30+ test cases):

- ✅ **test_project_setup.py** (3 tests)
  - Package imports
  - Version format
  - Subpackage imports

- ✅ **test_config.py** (18 tests)
  - Environment variable loading
  - YAML file loading
  - Config validation
  - Nested config merging
  - Error handling

- ✅ **test_logging.py** (12 tests)
  - JSON and text output
  - Log level filtering
  - Context binding
  - Structured logging

## Writing New Tests

### Test File Naming

- Test files: `test_*.py`
- Test classes: `Test*`
- Test functions: `test_*`

### Example Test

```python
# tests/unit/test_example.py
import pytest
from orion.module import function_to_test

def test_function_does_something():
    """Clear description of what is being tested."""
    result = function_to_test(input_value)
    assert result == expected_value

def test_function_handles_error():
    """Test error handling."""
    with pytest.raises(ValueError):
        function_to_test(invalid_input)

@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await async_function()
    assert result is not None
```

### Using Fixtures

```python
@pytest.fixture
def sample_config():
    """Provide sample config for tests."""
    return Config(
        data_provider=DataProviderConfig(api_key="test_key"),
        # ... other config
    )

def test_using_fixture(sample_config):
    """Use the fixture in a test."""
    assert sample_config.data_provider.api_key == "test_key"
```

## Continuous Integration (CI) Details

### GitHub Actions Workflow

The CI pipeline runs on every push and PR:

```yaml
jobs:
  test:
    - Run tests on Python 3.11 and 3.12
    - Cache dependencies for faster runs
    - Generate coverage report
    - Upload coverage to Codecov (optional)

  lint:
    - Check code formatting with Black
    - Lint with Ruff
    - Type check with mypy
```

### Matrix Testing

Tests run on multiple Python versions to ensure compatibility:
- Python 3.11
- Python 3.12

### Caching

Dependencies are cached to speed up CI runs:
- Cache key includes Python version and pyproject.toml hash
- Cache invalidates when dependencies change

## Troubleshooting

### Tests Pass Locally But Fail in CI

Common causes:
- **Environment differences**: Check Python version
- **Missing dependencies**: Ensure pyproject.toml is updated
- **File paths**: Use Path objects, not string concatenation
- **Timezone issues**: Use UTC in tests

### Pre-commit Hooks Not Running

```bash
# Reinstall hooks
pre-commit uninstall
pre-commit install

# Run manually
pre-commit run --all-files
```

### Coverage Too Low

```bash
# See which lines aren't covered
poetry run pytest --cov=orion --cov-report=html
open htmlcov/index.html  # View in browser
```

## Test Performance

### Current Performance

- **Unit tests**: ~1-2 seconds (all 30+ tests)
- **With coverage**: ~3-4 seconds
- **CI pipeline**: ~2-3 minutes (including dependency install)

### Optimization Tips

- Use `pytest-xdist` for parallel execution
- Mark slow tests: `@pytest.mark.slow`
- Skip integration tests locally: `pytest -m "not integration"`

## Test Markers

```python
# Mark integration test
@pytest.mark.integration
def test_real_api_call():
    pass

# Mark slow test
@pytest.mark.slow
def test_long_running():
    pass

# Mark asyncio test
@pytest.mark.asyncio
async def test_async():
    pass
```

Run specific markers:
```bash
pytest -m integration        # Only integration tests
pytest -m "not integration"  # Skip integration tests
pytest -m slow              # Only slow tests
```

## Next Steps

As more phases are completed, tests will be added for:

- **Phase 2**: Data models, providers, caching
- **Phase 3**: Technical indicators, pattern detection
- **Phase 4**: Strategy engine, rule evaluation
- **Phase 5**: Screening orchestration, notifications
- **Phase 6**: CLI, database storage
- **Phase 7**: Lambda deployment, cloud integration

---

**Questions?** Check the [Implementation Plan](design/implementation_plan.md) for detailed test specifications for each phase.
