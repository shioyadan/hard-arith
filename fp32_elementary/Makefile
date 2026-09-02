# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

RTL := $(CURDIR)/fp32_elementary.sv
TB := $(CURDIR)/test/tb_fp32_elementary.sv
REFERENCE := $(CURDIR)/test/reference.c
BUILD_DIR := $(CURDIR)/build/verilator
EXHAUSTIVE_BUILD_DIR := $(CURDIR)/build/verilator-exhaustive
EXHAUSTIVE_BINARY := $(EXHAUSTIVE_BUILD_DIR)/VFP32Elementary
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000
EXHAUSTIVE_THREADS ?= $(shell nproc)

.PHONY: all lint test exhaustive exhaustive-reduced exhaustive-active \
	exhaustive-build constants constants-check clean

all: test

lint:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Elementary $(RTL)

test: lint
	@mkdir -p $(BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32ElementaryTB --Mdir $(BUILD_DIR) \
		-GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		$(RTL) $(TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17' -LDFLAGS '-lquadmath -lm'
	$(BUILD_DIR)/VFP32ElementaryTB

$(EXHAUSTIVE_BINARY): $(RTL) $(REFERENCE) $(CURDIR)/test/exhaustive.cpp Makefile
	@mkdir -p $(EXHAUSTIVE_BUILD_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32Elementary --Mdir $(EXHAUSTIVE_BUILD_DIR) \
		$(RTL) $(CURDIR)/test/exhaustive.cpp $(REFERENCE) \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp -lquadmath -lm'

exhaustive-build: $(EXHAUSTIVE_BINARY)

# 精度違反が見つかっても両方の走査を完了し、最後に失敗を返す。
exhaustive: test $(EXHAUSTIVE_BINARY)
	@status=0; \
	$(EXHAUSTIVE_BINARY) --reduced-only --threads=$(EXHAUSTIVE_THREADS) \
		|| status=1; \
	$(EXHAUSTIVE_BINARY) --exp2-full-only --threads=$(EXHAUSTIVE_THREADS) \
		|| status=1; \
	exit $$status

exhaustive-reduced: $(EXHAUSTIVE_BINARY)
	$(EXHAUSTIVE_BINARY) --reduced-only --threads=$(EXHAUSTIVE_THREADS)

exhaustive-active: $(EXHAUSTIVE_BINARY)
	$(EXHAUSTIVE_BINARY) --exp2-active-only --threads=$(EXHAUSTIVE_THREADS)

constants:
	python3 tools/gen_constants.py --update $(RTL)

constants-check:
	python3 tools/gen_constants.py --check $(RTL)

clean:
	rm -rf build tools/__pycache__
