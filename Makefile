PYTHON ?= uv run python3
BRANCH ?=
PATHNAME ?=
BASE ?=
FORCE ?=
UV_CACHE_DIR ?= /private/tmp/tweb-uv-cache
PYTHONPYCACHEPREFIX ?= /private/tmp/tweb-pycache
OPTIONS ?= --cookie-from-browser zen --debug
# OPTIONS ?= --cookie-from-browser zen --debug --debug-block-colors
MODE ?=

WORKTREE_TARGETS := create remove
WORKTREE_INLINE_BRANCH := $(filter-out $(WORKTREE_TARGETS),$(MAKECMDGOALS))

ifeq ($(words $(filter $(WORKTREE_TARGETS),$(MAKECMDGOALS))),1)
ifneq ($(strip $(WORKTREE_INLINE_BRANCH)),)
ifeq ($(strip $(BRANCH)),)
override BRANCH := $(firstword $(WORKTREE_INLINE_BRANCH))
endif
$(foreach goal,$(WORKTREE_INLINE_BRANCH),$(eval $(goal):;@:))
endif
endif

.PHONY: all install wifi create remove clean clean-zero-head test

all::
	uv run tw $(OPTIONS) $(MODE)

install::
#	uv tool install --from . tweb
	python3 -m pip install .

wifi::
	uv run tw $(OPTIONS) $(MODE) http://captive.apple.com/

create:
	$(PYTHON) scripts/create_worktree.py $(BRANCH) $(if $(PATHNAME),--path $(PATHNAME),) $(if $(BASE),--base $(BASE),)

remove:
	$(PYTHON) scripts/remove_worktree.py $(BRANCH) $(if $(PATHNAME),--path $(PATHNAME),) $(if $(BASE),--base $(BASE),) $(if $(FORCE),--force,)

clean:: clean-worktree clean-zero-head

clean-worktree:
	$(PYTHON) scripts/clean_worktrees.py $(if $(BASE),--base $(BASE),) $(if $(FORCE),--force,)

clean-zero-head:
	@set -e; \
	paths="$$(git worktree list --porcelain | awk '\
	BEGIN { zero="0000000000000000000000000000000000000000"; path=""; head="" } \
	/^worktree / { if (path != "" && head == zero) print path; path=substr($$0, 10); head=""; next } \
	/^HEAD / { head=substr($$0, 6); next } \
	END { if (path != "" && head == zero) print path }' )"; \
	if [ -z "$$paths" ]; then \
		echo "no zero-head worktrees found"; \
		exit 0; \
	fi; \
	printf '%s\n' "$$paths" | while IFS= read -r path; do \
		[ -n "$$path" ] || continue; \
		git worktree remove --force "$$path"; \
		echo "removed worktree: $$path"; \
	done; \
	git worktree prune; \
	echo "pruned worktree metadata"

test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) PYTHONPYCACHEPREFIX=$(PYTHONPYCACHEPREFIX) uv run python3 -m unittest discover -s tests -p 'test_*.py'
