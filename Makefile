# Use the venv's Python by default. Override for non-Windows or system Python:
#   make release-patch PYTHON=python3
PYTHON ?= .venv/Scripts/python

.PHONY: help version test build dry-release-patch dry-release-minor dry-release-major release-patch release-minor release-major

help:
	@echo "Targets:"
	@echo "  make version              Print current version from setup.py"
	@echo "  make test                 Run unit tests (stdlib unittest)"
	@echo "  make build                Build sdist + wheel into dist/"
	@echo ""
	@echo "  make dry-release-patch    Show what release-patch would do (no commit / tag / push)"
	@echo "  make dry-release-minor    Show what release-minor would do"
	@echo "  make dry-release-major    Show what release-major would do"
	@echo ""
	@echo "  make release-patch        Bump X.Y.Z -> X.Y.Z+1, commit, tag, push (CI publishes to PyPI)"
	@echo "  make release-minor        Bump X.Y.Z -> X.Y+1.0, commit, tag, push"
	@echo "  make release-major        Bump X.Y.Z -> X+1.0.0, commit, tag, push"

version:
	@$(PYTHON) -c "import re; print(re.search(r'version=\"([^\"]+)\"', open('setup.py').read()).group(1))"

test:
	PYTHONPATH=. $(PYTHON) -m unittest discover -s tests -v

build:
	$(PYTHON) -m build

dry-release-patch:
	$(PYTHON) tools/release.py patch --dry-run

dry-release-minor:
	$(PYTHON) tools/release.py minor --dry-run

dry-release-major:
	$(PYTHON) tools/release.py major --dry-run

release-patch:
	$(PYTHON) tools/release.py patch

release-minor:
	$(PYTHON) tools/release.py minor

release-major:
	$(PYTHON) tools/release.py major
