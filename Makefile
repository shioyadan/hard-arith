# Copyright 2026 Ryota Shioya
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

UNITS := fp32_exp
CONSTANT_UNITS := fp32_exp

LINT_TARGETS := $(addprefix lint-,$(UNITS))
TEST_TARGETS := $(addprefix test-,$(UNITS))
CLEAN_TARGETS := $(addprefix clean-,$(UNITS))
CONSTANT_CHECK_TARGETS := $(addprefix constants-check-,$(CONSTANT_UNITS))

.PHONY: all lint test exhaustive clean constants-check

all: test

lint: $(LINT_TARGETS)

test: $(TEST_TARGETS)

exhaustive: exhaustive-fp32_exp

clean: $(CLEAN_TARGETS)

constants-check: $(CONSTANT_CHECK_TARGETS)

lint-%:
	$(MAKE) -C $* lint

test-%:
	$(MAKE) -C $* test

exhaustive-%:
	$(MAKE) -C $* exhaustive

clean-%:
	$(MAKE) -C $* clean

constants-check-%:
	$(MAKE) -C $* constants-check
