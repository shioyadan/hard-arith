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
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000
EXHAUSTIVE_THREADS ?= $(shell nproc)

.PHONY: all lint test exhaustive monotonic constants constants-check clean

all: test

lint:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Log2 $(RTL)

test: lint
	@mkdir -p $(BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Log2TB --Mdir $(BUILD_DIR) \
		-GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		$(RTL) $(TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17' -LDFLAGS '-lquadmath -lm'
	$(BUILD_DIR)/VFP32Log2TB

$(EXHAUSTIVE_BINARY): $(RTL) $(PACKAGE_DIR)/test/exhaustive.cpp $(PACKAGE_DIR)/Makefile
	@mkdir -p $(EXHAUSTIVE_BUILD_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32Log2 --Mdir $(EXHAUSTIVE_BUILD_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp -lquadmath -lm'

exhaustive: $(EXHAUSTIVE_BINARY)
	$(EXHAUSTIVE_BINARY) --threads=$(EXHAUSTIVE_THREADS)

monotonic: exhaustive

constants:
	python3 tools/gen_constants.py --update $(RTL)

constants-check:
	python3 tools/gen_constants.py --check $(RTL)

clean:
	rm -rf build tools/__pycache__
