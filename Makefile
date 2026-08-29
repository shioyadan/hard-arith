# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

UNITS := fp32_exp fp32_recip fp32_rsqrt fp32_log2 fp32_sincospi
CONSTANT_UNITS := fp32_exp fp32_recip fp32_rsqrt fp32_log2 fp32_sincospi
EXHAUSTIVE_UNITS := fp32_exp fp32_recip fp32_rsqrt fp32_log2 fp32_sincospi
MONOTONIC_UNITS := fp32_exp fp32_recip fp32_rsqrt fp32_log2

LINT_TARGETS := $(addprefix lint-,$(UNITS))
TEST_TARGETS := $(addprefix test-,$(UNITS))
CLEAN_TARGETS := $(addprefix clean-,$(UNITS))
CONSTANT_CHECK_TARGETS := $(addprefix constants-check-,$(CONSTANT_UNITS))
EXHAUSTIVE_TARGETS := $(addprefix exhaustive-,$(EXHAUSTIVE_UNITS))
MONOTONIC_TARGETS := $(addprefix monotonic-,$(MONOTONIC_UNITS))

.PHONY: all lint test exhaustive monotonic clean constants-check

all: test

lint: $(LINT_TARGETS)

test: $(TEST_TARGETS)

exhaustive: $(EXHAUSTIVE_TARGETS)

monotonic: $(MONOTONIC_TARGETS)

clean: $(CLEAN_TARGETS)

constants-check: $(CONSTANT_CHECK_TARGETS)

lint-%:
	$(MAKE) -C $* lint

test-%:
	$(MAKE) -C $* test

exhaustive-%:
	$(MAKE) -C $* exhaustive

monotonic-%:
	$(MAKE) -C $* monotonic

clean-%:
	$(MAKE) -C $* clean

constants-check-%:
	$(MAKE) -C $* constants-check
