# The active environment (INSTALL.md: conda activate oceanx); override with PYTHON=...
PYTHON ?= python
PYTEST = PYTHONPATH=src $(PYTHON) -m pytest
RUFF_TARGETS = src/oceanx tests scripts

.PHONY: lint typecheck frontend-build test test-contract test-e2e-offline test-wheel build release-manifest

# Faults only (syntax errors, undefined and unused names); style rules are not gated.
lint:
	$(PYTHON) -m ruff check --select E9,F $(RUFF_TARGETS)

typecheck:
	cd frontend/ocean-desktop && npm run check
	cd frontend/ocean-web && npm run check

frontend-build:
	cd frontend/ocean-desktop && npm run build
	cd frontend/ocean-web && npm run build

test:
	$(PYTEST) -q

test-contract: typecheck
	PYTHONPATH=src $(PYTHON) scripts/export_protocol_v2.py

test-e2e-offline:
	$(PYTEST) -q tests/test_oceanx

test-wheel:
	$(PYTHON) scripts/check_ocean_wheel_contents.py --dist dist

build: frontend-build
	$(PYTHON) -m build
	$(PYTHON) scripts/check_ocean_wheel_contents.py --dist dist

release-manifest:
	test -n "$(APP)" && test -n "$(VERSION)" && test -n "$(OUTPUT)"
	$(PYTHON) scripts/generate_desktop_release_manifest.py --app "$(APP)" --output "$(OUTPUT)" --version "$(VERSION)"
