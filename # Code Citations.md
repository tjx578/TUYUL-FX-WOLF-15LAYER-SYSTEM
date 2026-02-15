# Code Citations

## License: unknown

<https://github.com/Kaellas/Exam_Template_1st_Semester/blob/db6f6aea98d2bdb61720cfe3e626dc7e3fb7aa94/2.%20Regression%20Models.R>

Saya akan membuat GitHub Actions workflow yang sesuai dengan pipeline Wolf 15-Layer System — mencakup linting, testing, schema validation, constitutional boundary checks, dan deployment readiness.

````yaml
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\.github\workflows\wolf-pipeline-ci.yml
name: 🐺 Wolf 15-Layer CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

env:
  PYTHON_VERSION: "3.11"
  NODE_VERSION: "20"

# ──────────────────────────────────────────────────────────
# PHASE 1: LINT & STATIC ANALYSIS (Perception Gate)
# ──────────────────────────────────────────────────────────
jobs:
  phase-1-lint:
    name: "Phase 1 · Lint & Static Analysis"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install flake8 mypy black isort

      - name: 🔍 Black (formatting check)
        run: black --check --diff .

      - name: 🔍 isort (import order)
        run: isort --check-only --diff .

      - name: 🔍 Flake8 (lint)
        run: flake8 . --max-line-length=120 --exclude=.venv,node_modules,__pycache__,.git

      - name: 🔍 Mypy (type check - critical modules)
        run: |
          mypy constitution/ --ignore-missing-imports --no-error-summary || true
          mypy risk/ --ignore-missing-imports --no-error-summary || true
          mypy pipeline/ --ignore-missing-imports --no-error-summary || true

  # ──────────────────────────────────────────────────────────
  # PHASE 2: CONSTITUTIONAL BOUNDARY VALIDATION
  # ──────────────────────────────────────────────────────────
  phase
```


## License: unknown

https://github.com/Kaellas/Exam_Template_1st_Semester/blob/db6f6aea98d2bdb61720cfe3e626dc7e3fb7aa94/2.%20Regression%20Models.R

```


Saya akan membuat GitHub Actions workflow yang sesuai dengan pipeline Wolf 15-Layer System — mencakup linting, testing, schema validation, constitutional boundary checks, dan deployment readiness.

````yaml
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\.github\workflows\wolf-pipeline-ci.yml
name: 🐺 Wolf 15-Layer CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

env:
  PYTHON_VERSION: "3.11"
  NODE_VERSION: "20"

# ──────────────────────────────────────────────────────────
# PHASE 1: LINT & STATIC ANALYSIS (Perception Gate)
# ──────────────────────────────────────────────────────────
jobs:
  phase-1-lint:
    name: "Phase 1 · Lint & Static Analysis"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install flake8 mypy black isort

      - name: 🔍 Black (formatting check)
        run: black --check --diff .

      - name: 🔍 isort (import order)
        run: isort --check-only --diff .

      - name: 🔍 Flake8 (lint)
        run: flake8 . --max-line-length=120 --exclude=.venv,node_modules,__pycache__,.git

      - name: 🔍 Mypy (type check - critical modules)
        run: |
          mypy constitution/ --ignore-missing-imports --no-error-summary || true
          mypy risk/ --ignore-missing-imports --no-error-summary || true
          mypy pipeline/ --ignore-missing-imports --no-error-summary || true

  # ──────────────────────────────────────────────────────────
  # PHASE 2: CONSTITUTIONAL BOUNDARY VALIDATION
  # ──────────────────────────────────────────────────────────
  phase
```


## License: unknown

https://github.com/Kaellas/Exam_Template_1st_Semester/blob/db6f6aea98d2bdb61720cfe3e626dc7e3fb7aa94/2.%20Regression%20Models.R

```


Saya akan membuat GitHub Actions workflow yang sesuai dengan pipeline Wolf 15-Layer System — mencakup linting, testing, schema validation, constitutional boundary checks, dan deployment readiness.

````yaml
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\.github\workflows\wolf-pipeline-ci.yml
name: 🐺 Wolf 15-Layer CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

env:
  PYTHON_VERSION: "3.11"
  NODE_VERSION: "20"

# ──────────────────────────────────────────────────────────
# PHASE 1: LINT & STATIC ANALYSIS (Perception Gate)
# ──────────────────────────────────────────────────────────
jobs:
  phase-1-lint:
    name: "Phase 1 · Lint & Static Analysis"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install flake8 mypy black isort

      - name: 🔍 Black (formatting check)
        run: black --check --diff .

      - name: 🔍 isort (import order)
        run: isort --check-only --diff .

      - name: 🔍 Flake8 (lint)
        run: flake8 . --max-line-length=120 --exclude=.venv,node_modules,__pycache__,.git

      - name: 🔍 Mypy (type check - critical modules)
        run: |
          mypy constitution/ --ignore-missing-imports --no-error-summary || true
          mypy risk/ --ignore-missing-imports --no-error-summary || true
          mypy pipeline/ --ignore-missing-imports --no-error-summary || true

  # ──────────────────────────────────────────────────────────
  # PHASE 2: CONSTITUTIONAL BOUNDARY VALIDATION
  # ──────────────────────────────────────────────────────────
  phase
```


## License: unknown

https://github.com/Kaellas/Exam_Template_1st_Semester/blob/db6f6aea98d2bdb61720cfe3e626dc7e3fb7aa94/2.%20Regression%20Models.R

```


Saya akan membuat GitHub Actions workflow yang sesuai dengan pipeline Wolf 15-Layer System — mencakup linting, testing, schema validation, constitutional boundary checks, dan deployment readiness.

````yaml
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\.github\workflows\wolf-pipeline-ci.yml
name: 🐺 Wolf 15-Layer CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

env:
  PYTHON_VERSION: "3.11"
  NODE_VERSION: "20"

# ──────────────────────────────────────────────────────────
# PHASE 1: LINT & STATIC ANALYSIS (Perception Gate)
# ──────────────────────────────────────────────────────────
jobs:
  phase-1-lint:
    name: "Phase 1 · Lint & Static Analysis"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install flake8 mypy black isort

      - name: 🔍 Black (formatting check)
        run: black --check --diff .

      - name: 🔍 isort (import order)
        run: isort --check-only --diff .

      - name: 🔍 Flake8 (lint)
        run: flake8 . --max-line-length=120 --exclude=.venv,node_modules,__pycache__,.git

      - name: 🔍 Mypy (type check - critical modules)
        run: |
          mypy constitution/ --ignore-missing-imports --no-error-summary || true
          mypy risk/ --ignore-missing-imports --no-error-summary || true
          mypy pipeline/ --ignore-missing-imports --no-error-summary || true

  # ──────────────────────────────────────────────────────────
  # PHASE 2: CONSTITUTIONAL BOUNDARY VALIDATION
  # ──────────────────────────────────────────────────────────
  phase
```


## License: unknown

https://github.com/Kaellas/Exam_Template_1st_Semester/blob/db6f6aea98d2bdb61720cfe3e626dc7e3fb7aa94/2.%20Regression%20Models.R

```


Saya akan membuat GitHub Actions workflow yang sesuai dengan pipeline Wolf 15-Layer System — mencakup linting, testing, schema validation, constitutional boundary checks, dan deployment readiness.

````yaml
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\.github\workflows\wolf-pipeline-ci.yml
name: 🐺 Wolf 15-Layer CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

env:
  PYTHON_VERSION: "3.11"
  NODE_VERSION: "20"

# ──────────────────────────────────────────────────────────
# PHASE 1: LINT & STATIC ANALYSIS (Perception Gate)
# ──────────────────────────────────────────────────────────
jobs:
  phase-1-lint:
    name: "Phase 1 · Lint & Static Analysis"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install flake8 mypy black isort

      - name: 🔍 Black (formatting check)
        run: black --check --diff .

      - name: 🔍 isort (import order)
        run: isort --check-only --diff .

      - name: 🔍 Flake8 (lint)
        run: flake8 . --max-line-length=120 --exclude=.venv,node_modules,__pycache__,.git

      - name: 🔍 Mypy (type check - critical modules)
        run: |
          mypy constitution/ --ignore-missing-imports --no-error-summary || true
          mypy risk/ --ignore-missing-imports --no-error-summary || true
          mypy pipeline/ --ignore-missing-imports --no-error-summary || true

  # ──────────────────────────────────────────────────────────
  # PHASE 2: CONSTITUTIONAL BOUNDARY VALIDATION
  # ──────────────────────────────────────────────────────────
  phase-2-constitutional-boundary:
    name: "Phase 2 · Constitutional Boundary Check"
    runs-on: ubuntu-latest
    needs: phase-1-lint
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: 🔒 Rule 1 — analysis/ must NOT contain execution logic
        run: |
          echo "Checking analysis/ for forbidden execution patterns..."
          VIOLATIONS=$(grep -rn \
            -e "place_order" \
            -e "execute_trade" \
            -e "send_order" \
            -e "market_execution" \
            -e "mt4_send" \
            -e "mt5_send" \
            --include="*.py" analysis/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: analysis/ contains execution logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ analysis/ clean — no execution side-effects"

      - name: 🔒 Rule 2 — execution/ must NOT contain strategy logic
        run: |
          echo "Checking execution/ for forbidden strategy patterns..."
          VIOLATIONS=$(grep -rn \
            -e "calculate_signal" \
            -e "market_direction" \
            -e "trend_analysis" \
            -e "wolf_score" \
            -e "confluence" \
            -e "generate_verdict" \
            --include="*.py" execution/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: execution/ contains strategy logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ execution/ clean — blind executor only"

      - name: 🔒 Rule 3 — dashboard/ must NOT override L12
        run: |
          echo "Checking dashboard/ for L12 override patterns..."
          VIOLATIONS=$(grep -rn \
            -e "override_verdict" \
            -e "force_execute" \
            -e "bypass_gate" \
            -e "skip_constitution" \
            -e "ignore_l12" \
            --include="*.py" dashboard/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: dashboard/ attempts L12 override!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ dashboard/ clean — read-only governor"

      - name: 🔒 Rule 4 — journal/ must be append-only
        run: |
          echo "Checking journal/ for mutation patterns..."
          VIOLATIONS=$(grep -rn \
            -e "\.delete(" \
            -e "\.update(" \
            -e "\.remove(" \
            -e "DELETE FROM" \
            -e "UPDATE.*SET" \
            -e "truncate" \
            --include="*.py" journal/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: journal/ contains mutation logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ journal/ clean — immutable audit trail"

      - name: 🔒 Rule 5 — ea_interface/ must NOT contain decision logic
        run: |
          echo "Checking ea_interface/ for decision patterns..."
          VIOLATIONS=$(grep -rn \
            -e "generate_verdict" \
            -e "wolf_score" \
            -e "should_trade" \
            -e "analyze_market" \
            --include="*.py" ea_interface/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: ea_interface/ contains decision logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ ea_interface/ clean — executor only"

      - name: 🔒 Rule 6 — No secrets in codebase
        run: |
          echo "Checking for hardcoded secrets..."
          VIOLATIONS=$(grep -rn \
            -e "FINNHUB_API_KEY\s*=" \
            -e "TELEGRAM_BOT_TOKEN\s*=" \
            -e "REDIS_PASSWORD\s*=" \
            -e "JWT_SECRET\s*=" \
            --include="*.py" \
            --exclude-dir=.venv \
            --exclude="*.example" \
            . || true)
          # Filter out os.getenv / os.environ patterns (these are safe)
          REAL_VIOLATIONS=$(echo "$VIOLATIONS" | grep -v "os\.getenv\|os\.environ\|\.env\|config\.\|#" || true)
          if [ -n "$REAL_VIOLATIONS" ]; then
            echo "❌ SECURITY VIOLATION: Hardcoded secrets detected!"
            echo "$REAL_VIOLATIONS"
            exit 1
          fi
          echo "✅ No hardcoded secrets found"

  # ──────────────────────────────────────────────────────────
  # PHASE 3: SCHEMA VALIDATION
  # ──────────────────────────────────────────────────────────
```


## License: unknown

https://github.com/Kaellas/Exam_Template_1st_Semester/blob/db6f6aea98d2bdb61720cfe3e626dc7e3fb7aa94/2.%20Regression%20Models.R

```


Saya akan membuat GitHub Actions workflow yang sesuai dengan pipeline Wolf 15-Layer System — mencakup linting, testing, schema validation, constitutional boundary checks, dan deployment readiness.

````yaml
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\.github\workflows\wolf-pipeline-ci.yml
name: 🐺 Wolf 15-Layer CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

env:
  PYTHON_VERSION: "3.11"
  NODE_VERSION: "20"

# ──────────────────────────────────────────────────────────
# PHASE 1: LINT & STATIC ANALYSIS (Perception Gate)
# ──────────────────────────────────────────────────────────
jobs:
  phase-1-lint:
    name: "Phase 1 · Lint & Static Analysis"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install flake8 mypy black isort

      - name: 🔍 Black (formatting check)
        run: black --check --diff .

      - name: 🔍 isort (import order)
        run: isort --check-only --diff .

      - name: 🔍 Flake8 (lint)
        run: flake8 . --max-line-length=120 --exclude=.venv,node_modules,__pycache__,.git

      - name: 🔍 Mypy (type check - critical modules)
        run: |
          mypy constitution/ --ignore-missing-imports --no-error-summary || true
          mypy risk/ --ignore-missing-imports --no-error-summary || true
          mypy pipeline/ --ignore-missing-imports --no-error-summary || true

  # ──────────────────────────────────────────────────────────
  # PHASE 2: CONSTITUTIONAL BOUNDARY VALIDATION
  # ──────────────────────────────────────────────────────────
  phase-2-constitutional-boundary:
    name: "Phase 2 · Constitutional Boundary Check"
    runs-on: ubuntu-latest
    needs: phase-1-lint
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: 🔒 Rule 1 — analysis/ must NOT contain execution logic
        run: |
          echo "Checking analysis/ for forbidden execution patterns..."
          VIOLATIONS=$(grep -rn \
            -e "place_order" \
            -e "execute_trade" \
            -e "send_order" \
            -e "market_execution" \
            -e "mt4_send" \
            -e "mt5_send" \
            --include="*.py" analysis/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: analysis/ contains execution logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ analysis/ clean — no execution side-effects"

      - name: 🔒 Rule 2 — execution/ must NOT contain strategy logic
        run: |
          echo "Checking execution/ for forbidden strategy patterns..."
          VIOLATIONS=$(grep -rn \
            -e "calculate_signal" \
            -e "market_direction" \
            -e "trend_analysis" \
            -e "wolf_score" \
            -e "confluence" \
            -e "generate_verdict" \
            --include="*.py" execution/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: execution/ contains strategy logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ execution/ clean — blind executor only"

      - name: 🔒 Rule 3 — dashboard/ must NOT override L12
        run: |
          echo "Checking dashboard/ for L12 override patterns..."
          VIOLATIONS=$(grep -rn \
            -e "override_verdict" \
            -e "force_execute" \
            -e "bypass_gate" \
            -e "skip_constitution" \
            -e "ignore_l12" \
            --include="*.py" dashboard/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: dashboard/ attempts L12 override!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ dashboard/ clean — read-only governor"

      - name: 🔒 Rule 4 — journal/ must be append-only
        run: |
          echo "Checking journal/ for mutation patterns..."
          VIOLATIONS=$(grep -rn \
            -e "\.delete(" \
            -e "\.update(" \
            -e "\.remove(" \
            -e "DELETE FROM" \
            -e "UPDATE.*SET" \
            -e "truncate" \
            --include="*.py" journal/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: journal/ contains mutation logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ journal/ clean — immutable audit trail"

      - name: 🔒 Rule 5 — ea_interface/ must NOT contain decision logic
        run: |
          echo "Checking ea_interface/ for decision patterns..."
          VIOLATIONS=$(grep -rn \
            -e "generate_verdict" \
            -e "wolf_score" \
            -e "should_trade" \
            -e "analyze_market" \
            --include="*.py" ea_interface/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: ea_interface/ contains decision logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ ea_interface/ clean — executor only"

      - name: 🔒 Rule 6 — No secrets in codebase
        run: |
          echo "Checking for hardcoded secrets..."
          VIOLATIONS=$(grep -rn \
            -e "FINNHUB_API_KEY\s*=" \
            -e "TELEGRAM_BOT_TOKEN\s*=" \
            -e "REDIS_PASSWORD\s*=" \
            -e "JWT_SECRET\s*=" \
            --include="*.py" \
            --exclude-dir=.venv \
            --exclude="*.example" \
            . || true)
          # Filter out os.getenv / os.environ patterns (these are safe)
          REAL_VIOLATIONS=$(echo "$VIOLATIONS" | grep -v "os\.getenv\|os\.environ\|\.env\|config\.\|#" || true)
          if [ -n "$REAL_VIOLATIONS" ]; then
            echo "❌ SECURITY VIOLATION: Hardcoded secrets detected!"
            echo "$REAL_VIOLATIONS"
            exit 1
          fi
          echo "✅ No hardcoded secrets found"

  # ──────────────────────────────────────────────────────────
  # PHASE 3: SCHEMA VALIDATION
  # ──────────────────────────────────────────────────────────
```


## License: unknown

https://github.com/Kaellas/Exam_Template_1st_Semester/blob/db6f6aea98d2bdb61720cfe3e626dc7e3fb7aa94/2.%20Regression%20Models.R

```


Saya akan membuat GitHub Actions workflow yang sesuai dengan pipeline Wolf 15-Layer System — mencakup linting, testing, schema validation, constitutional boundary checks, dan deployment readiness.

````yaml
// filepath: c:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\.github\workflows\wolf-pipeline-ci.yml
name: 🐺 Wolf 15-Layer CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

env:
  PYTHON_VERSION: "3.11"
  NODE_VERSION: "20"

# ──────────────────────────────────────────────────────────
# PHASE 1: LINT & STATIC ANALYSIS (Perception Gate)
# ──────────────────────────────────────────────────────────
jobs:
  phase-1-lint:
    name: "Phase 1 · Lint & Static Analysis"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install flake8 mypy black isort

      - name: 🔍 Black (formatting check)
        run: black --check --diff .

      - name: 🔍 isort (import order)
        run: isort --check-only --diff .

      - name: 🔍 Flake8 (lint)
        run: flake8 . --max-line-length=120 --exclude=.venv,node_modules,__pycache__,.git

      - name: 🔍 Mypy (type check - critical modules)
        run: |
          mypy constitution/ --ignore-missing-imports --no-error-summary || true
          mypy risk/ --ignore-missing-imports --no-error-summary || true
          mypy pipeline/ --ignore-missing-imports --no-error-summary || true

  # ──────────────────────────────────────────────────────────
  # PHASE 2: CONSTITUTIONAL BOUNDARY VALIDATION
  # ──────────────────────────────────────────────────────────
  phase-2-constitutional-boundary:
    name: "Phase 2 · Constitutional Boundary Check"
    runs-on: ubuntu-latest
    needs: phase-1-lint
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: 🔒 Rule 1 — analysis/ must NOT contain execution logic
        run: |
          echo "Checking analysis/ for forbidden execution patterns..."
          VIOLATIONS=$(grep -rn \
            -e "place_order" \
            -e "execute_trade" \
            -e "send_order" \
            -e "market_execution" \
            -e "mt4_send" \
            -e "mt5_send" \
            --include="*.py" analysis/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: analysis/ contains execution logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ analysis/ clean — no execution side-effects"

      - name: 🔒 Rule 2 — execution/ must NOT contain strategy logic
        run: |
          echo "Checking execution/ for forbidden strategy patterns..."
          VIOLATIONS=$(grep -rn \
            -e "calculate_signal" \
            -e "market_direction" \
            -e "trend_analysis" \
            -e "wolf_score" \
            -e "confluence" \
            -e "generate_verdict" \
            --include="*.py" execution/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: execution/ contains strategy logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ execution/ clean — blind executor only"

      - name: 🔒 Rule 3 — dashboard/ must NOT override L12
        run: |
          echo "Checking dashboard/ for L12 override patterns..."
          VIOLATIONS=$(grep -rn \
            -e "override_verdict" \
            -e "force_execute" \
            -e "bypass_gate" \
            -e "skip_constitution" \
            -e "ignore_l12" \
            --include="*.py" dashboard/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: dashboard/ attempts L12 override!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ dashboard/ clean — read-only governor"

      - name: 🔒 Rule 4 — journal/ must be append-only
        run: |
          echo "Checking journal/ for mutation patterns..."
          VIOLATIONS=$(grep -rn \
            -e "\.delete(" \
            -e "\.update(" \
            -e "\.remove(" \
            -e "DELETE FROM" \
            -e "UPDATE.*SET" \
            -e "truncate" \
            --include="*.py" journal/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: journal/ contains mutation logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ journal/ clean — immutable audit trail"

      - name: 🔒 Rule 5 — ea_interface/ must NOT contain decision logic
        run: |
          echo "Checking ea_interface/ for decision patterns..."
          VIOLATIONS=$(grep -rn \
            -e "generate_verdict" \
            -e "wolf_score" \
            -e "should_trade" \
            -e "analyze_market" \
            --include="*.py" ea_interface/ || true)
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ CONSTITUTIONAL VIOLATION: ea_interface/ contains decision logic!"
            echo "$VIOLATIONS"
            exit 1
          fi
          echo "✅ ea_interface/ clean — executor only"

      - name: 🔒 Rule 6 — No secrets in codebase
        run: |
          echo "Checking for hardcoded secrets..."
          VIOLATIONS=$(grep -rn \
            -e "FINNHUB_API_KEY\s*=" \
            -e "TELEGRAM_BOT_TOKEN\s*=" \
            -e "REDIS_PASSWORD\s*=" \
            -e "JWT_SECRET\s*=" \
            --include="*.py" \
            --exclude-dir=.venv \
            --exclude="*.example" \
            . || true)
          # Filter out os.getenv / os.environ patterns (these are safe)
          REAL_VIOLATIONS=$(echo "$VIOLATIONS" | grep -v "os\.getenv\|os\.environ\|\.env\|config\.\|#" || true)
          if [ -n "$REAL_VIOLATIONS" ]; then
            echo "❌ SECURITY VIOLATION: Hardcoded secrets detected!"
            echo "$REAL_VIOLATIONS"
            exit 1
          fi
          echo "✅ No hardcoded secrets found"

  # ──────────────────────────────────────────────────────────
  # PHASE 3: SCHEMA VALIDATION
  # ──────────────────────────────────────────────────────────
```

