# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PACKAGE_DIR := $(CURDIR)
RTL := $(PACKAGE_DIR)/fp32_log2.sv
TB := $(PACKAGE_DIR)/test/tb_fp32_log2.sv
REFERENCE := $(PACKAGE_DIR)/test/reference.c
BUILD_DIR := $(PACKAGE_DIR)/build/verilator
EXHAUSTIVE_BUILD_DIR := $(PACKAGE_DIR)/build/verilator-exhaustive
EXHAUSTIVE_BINARY := $(EXHAUSTIVE_BUILD_DIR)/VFP32Log2
LITE_RTL := $(PACKAGE_DIR)/fp32_log2_lite.sv
LITE_TB := $(PACKAGE_DIR)/test/tb_fp32_log2_lite.sv
LITE_BUILD_DIR := $(PACKAGE_DIR)/build/verilator-lite
LITE_EXHAUSTIVE_BUILD_DIR := $(PACKAGE_DIR)/build/verilator-lite-exhaustive
LITE_EXHAUSTIVE_BINARY := $(LITE_EXHAUSTIVE_BUILD_DIR)/VFP32Log2Lite
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000
EXHAUSTIVE_THREADS ?= $(shell nproc)

.PHONY: all lint lint-faithful lint-lite test test-faithful test-lite \
	exhaustive exhaustive-faithful exhaustive-lite monotonic \
	constants constants-check clean

all: test

lint: lint-faithful lint-lite

lint-faithful:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Log2 $(RTL)

lint-lite:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Log2Lite $(LITE_RTL)

test: test-faithful test-lite

test-faithful: lint-faithful
	@mkdir -p $(BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Log2TB --Mdir $(BUILD_DIR) \
		-GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		$(RTL) $(TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17' -LDFLAGS '-lquadmath -lm'
	$(BUILD_DIR)/VFP32Log2TB

test-lite: lint-lite
	@mkdir -p $(LITE_BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Log2LiteTB \
		--Mdir $(LITE_BUILD_DIR) \
		-GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		$(LITE_RTL) $(LITE_TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17' -LDFLAGS '-lquadmath -lm'
	$(LITE_BUILD_DIR)/VFP32Log2LiteTB

$(EXHAUSTIVE_BINARY): $(RTL) $(PACKAGE_DIR)/test/exhaustive.cpp $(PACKAGE_DIR)/Makefile
	@mkdir -p $(EXHAUSTIVE_BUILD_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32Log2 --Mdir $(EXHAUSTIVE_BUILD_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp -lquadmath -lm'

exhaustive: exhaustive-faithful exhaustive-lite

exhaustive-faithful: $(EXHAUSTIVE_BINARY)
	$(EXHAUSTIVE_BINARY) --threads=$(EXHAUSTIVE_THREADS)

$(LITE_EXHAUSTIVE_BINARY): $(LITE_RTL) $(PACKAGE_DIR)/test/exhaustive_lite.cpp $(PACKAGE_DIR)/Makefile
	@mkdir -p $(LITE_EXHAUSTIVE_BUILD_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32Log2Lite --Mdir $(LITE_EXHAUSTIVE_BUILD_DIR) \
		$(LITE_RTL) $(PACKAGE_DIR)/test/exhaustive_lite.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp -lquadmath -lm'

exhaustive-lite: $(LITE_EXHAUSTIVE_BINARY)
	$(LITE_EXHAUSTIVE_BINARY) --threads=$(EXHAUSTIVE_THREADS)

monotonic: exhaustive

constants:
	python3 tools/gen_constants.py --update $(RTL)
	python3 tools/gen_lite_constants.py --update $(LITE_RTL)

constants-check:
	python3 tools/gen_constants.py --check $(RTL)
	python3 tools/gen_lite_constants.py --check $(LITE_RTL)

clean:
	rm -rf build tools/__pycache__
