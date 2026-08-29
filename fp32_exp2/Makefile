# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PACKAGE_DIR := $(CURDIR)
RTL := $(PACKAGE_DIR)/fp32_exp2.sv
TB := $(PACKAGE_DIR)/test/tb_fp32_exp2.sv
REFERENCE := $(PACKAGE_DIR)/test/reference.c
BUILD_DIR := $(PACKAGE_DIR)/build/verilator
EXHAUSTIVE_USE_MPFR ?= $(if $(wildcard /usr/include/mpfr.h),1,0)
EXHAUSTIVE_BUILD_TAG := $(if $(filter 1,$(EXHAUSTIVE_USE_MPFR)),-mpfr,)
EXHAUSTIVE_BUILD_DIR := $(PACKAGE_DIR)/build/verilator-exhaustive$(EXHAUSTIVE_BUILD_TAG)
EXHAUSTIVE_BINARY := $(EXHAUSTIVE_BUILD_DIR)/VFP32Exp
MONOTONIC_BUILD_DIR := $(PACKAGE_DIR)/build/verilator-monotonic
MONOTONIC_BINARY := $(MONOTONIC_BUILD_DIR)/VFP32Exp
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000
EXHAUSTIVE_THREADS ?= $(shell nproc)
MONOTONIC_THREADS ?= $(shell nproc)

ifeq ($(EXHAUSTIVE_USE_MPFR),1)
EXHAUSTIVE_CFLAGS := -DFP32_EXP_USE_MPFR
EXHAUSTIVE_LDFLAGS := -lmpfr -lgmp
EXHAUSTIVE_ARGS := --mpfr-near-boundary
endif

.PHONY: all lint test exhaustive exhaustive-active exhaustive-build monotonic monotonic-build constants constants-check clean

all: test

lint:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Exp2 $(RTL)

test: lint
	@mkdir -p $(BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Exp2TB --Mdir $(BUILD_DIR) \
		-GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		$(RTL) $(TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17' -LDFLAGS '-lquadmath -lm'
	$(BUILD_DIR)/VFP32Exp2TB

$(EXHAUSTIVE_BINARY): $(RTL) $(PACKAGE_DIR)/test/exhaustive.cpp $(PACKAGE_DIR)/../fp32_exp/test/exhaustive.cpp $(PACKAGE_DIR)/Makefile
	@mkdir -p $(EXHAUSTIVE_BUILD_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32Exp2 --prefix VFP32Exp --Mdir $(EXHAUSTIVE_BUILD_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp $(EXHAUSTIVE_CFLAGS)' \
		-LDFLAGS '-fopenmp $(EXHAUSTIVE_LDFLAGS)'

exhaustive-build: $(EXHAUSTIVE_BINARY)

exhaustive: $(EXHAUSTIVE_BINARY)
	$(EXHAUSTIVE_BINARY) --full --threads=$(EXHAUSTIVE_THREADS) $(EXHAUSTIVE_ARGS)

exhaustive-active: $(EXHAUSTIVE_BINARY)
	$(EXHAUSTIVE_BINARY) --active --threads=$(EXHAUSTIVE_THREADS) $(EXHAUSTIVE_ARGS)

$(MONOTONIC_BINARY): $(RTL) $(PACKAGE_DIR)/test/monotonic.cpp $(PACKAGE_DIR)/../fp32_exp/test/monotonic.cpp $(PACKAGE_DIR)/Makefile
	@mkdir -p $(MONOTONIC_BUILD_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32Exp2 --prefix VFP32Exp --Mdir $(MONOTONIC_BUILD_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/monotonic.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp'

monotonic-build: $(MONOTONIC_BINARY)

monotonic: $(MONOTONIC_BINARY)
	$(MONOTONIC_BINARY) --threads=$(MONOTONIC_THREADS)

constants:
	python3 tools/gen_constants.py

constants-check:
	python3 $(PACKAGE_DIR)/tools/gen_constants.py --check $(RTL)

clean:
	rm -rf build tools/__pycache__
