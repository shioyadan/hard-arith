# Copyright 2026 Ryota Shioya
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PACKAGE_DIR := $(CURDIR)
RTL := $(PACKAGE_DIR)/fp32_exp.sv
TB := $(PACKAGE_DIR)/test/tb_fp32_exp.sv
REFERENCE := $(PACKAGE_DIR)/test/reference.c
BUILD_DIR := $(PACKAGE_DIR)/build/verilator
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000

.PHONY: all lint test constants constants-check clean

all: test

lint:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32Exp $(RTL)

test: lint
	@mkdir -p $(BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32ExpTB --Mdir $(BUILD_DIR) \
		-GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		$(RTL) $(TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17' -LDFLAGS '-lquadmath -lm'
	$(BUILD_DIR)/VFP32ExpTB

constants:
	python3 tools/gen_constants.py

constants-check:
	python3 $(PACKAGE_DIR)/tools/gen_constants.py --check $(RTL)

clean:
	rm -rf build
