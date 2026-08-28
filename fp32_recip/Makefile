# Copyright 2026 Ryota Shioya
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PACKAGE_DIR := $(CURDIR)
RTL := $(PACKAGE_DIR)/fp32_recip.sv
TB := $(PACKAGE_DIR)/test/tb_fp32_recip.sv
REFERENCE := $(PACKAGE_DIR)/test/reference.c
BUILD_DIR := $(PACKAGE_DIR)/build/verilator
EXHAUSTIVE_BUILD_DIR := $(PACKAGE_DIR)/build/verilator-exhaustive
EXHAUSTIVE_BINARY := $(EXHAUSTIVE_BUILD_DIR)/VFP32Recip
MONOTONIC_BUILD_DIR := $(PACKAGE_DIR)/build/verilator-monotonic
MONOTONIC_BINARY := $(MONOTONIC_BUILD_DIR)/VFP32Recip
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000
EXHAUSTIVE_THREADS ?= $(shell nproc)

.PHONY: all lint test exhaustive exhaustive-build monotonic monotonic-build constants constants-check clean

all: test

lint:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Recip $(RTL)

test: lint
	@mkdir -p $(BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32RecipTB --Mdir $(BUILD_DIR) \
		-GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		$(RTL) $(TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17'
	$(BUILD_DIR)/VFP32RecipTB

$(EXHAUSTIVE_BINARY): $(RTL) $(PACKAGE_DIR)/test/exhaustive.cpp $(PACKAGE_DIR)/Makefile
	@mkdir -p $(EXHAUSTIVE_BUILD_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32Recip --Mdir $(EXHAUSTIVE_BUILD_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp'

exhaustive-build: $(EXHAUSTIVE_BINARY)

exhaustive: $(EXHAUSTIVE_BINARY)
	$(EXHAUSTIVE_BINARY) --threads=$(EXHAUSTIVE_THREADS)

$(MONOTONIC_BINARY): $(RTL) $(PACKAGE_DIR)/test/monotonic.cpp $(PACKAGE_DIR)/Makefile
	@mkdir -p $(MONOTONIC_BUILD_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32Recip --Mdir $(MONOTONIC_BUILD_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/monotonic.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20'

monotonic-build: $(MONOTONIC_BINARY)

monotonic: $(MONOTONIC_BINARY)
	$(MONOTONIC_BINARY)

constants:
	python3 tools/gen_constants.py

constants-check:
	python3 $(PACKAGE_DIR)/tools/gen_constants.py --check $(RTL)

clean:
	rm -rf build tools/__pycache__
