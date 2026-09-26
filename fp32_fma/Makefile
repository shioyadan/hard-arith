# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PACKAGE_DIR := $(CURDIR)
BUILD_DIR := $(PACKAGE_DIR)/build/verilator-rounding
RTL := $(PACKAGE_DIR)/fp32_fma.sv
BINARY := $(BUILD_DIR)/VFP32FMA
RANDOM_CYCLES ?= 200000
MPFR_CFLAGS ?=
MPFR_LDFLAGS ?= -lmpfr -lgmp
BUILD_JOBS ?= 4

.PHONY: all lint test stress clean
all: test

lint:
	verilator --lint-only --Wall --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32FMA $(RTL)

$(BINARY): $(RTL) $(PACKAGE_DIR)/test/test.cpp $(PACKAGE_DIR)/test/reference.hpp Makefile
	@mkdir -p $(BUILD_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) \
		--Wall --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32FMA --Mdir $(BUILD_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/test.cpp \
		-CFLAGS '-O2 -std=c++17 $(MPFR_CFLAGS)' -LDFLAGS '$(MPFR_LDFLAGS)'

test: lint $(BINARY)
	$(BINARY) --random=$(RANDOM_CYCLES)

stress: lint $(BINARY)
	$(BINARY) --random=5000000 --all-exponents

clean:
	rm -rf -- build
