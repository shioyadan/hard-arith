# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PACKAGE_DIR := $(CURDIR)
BUILD_DIR := $(PACKAGE_DIR)/build/verilator-rounding
RTL := $(PACKAGE_DIR)/fp64_fma.sv
BINARY := $(BUILD_DIR)/VFP64FMA
RANDOM_CYCLES ?= 200000
MPFR_CFLAGS ?=
MPFR_LDFLAGS ?= -lmpfr -lgmp
BUILD_JOBS ?= 4

.PHONY: all lint test stress clean
all: test

lint:
	verilator --lint-only --Wall --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP64FMA $(RTL)

$(BINARY): $(RTL) $(PACKAGE_DIR)/test/test.cpp $(PACKAGE_DIR)/test/reference.hpp Makefile
	@mkdir -p $(BUILD_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) \
		--Wall --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP64FMA --Mdir $(BUILD_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/test.cpp \
		-CFLAGS '-O2 -std=c++17 $(MPFR_CFLAGS)' -LDFLAGS '$(MPFR_LDFLAGS)'

test: lint $(BINARY)
	$(BINARY) --random=$(RANDOM_CYCLES)

stress: lint $(BINARY)
	$(BINARY) --random=1000000 --sweep-exponents

clean:
	rm -rf -- build
