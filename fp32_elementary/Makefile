# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

RTL := $(CURDIR)/fp32_elementary.sv
TB := $(CURDIR)/test/tb_fp32_elementary.sv
REFERENCE := $(CURDIR)/test/reference.c
BUILD_DIR := $(CURDIR)/build/verilator
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000

.PHONY: all lint test constants constants-check clean

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

constants:
	python3 tools/gen_constants.py --update $(RTL)

constants-check:
	python3 tools/gen_constants.py --check $(RTL)

clean:
	rm -rf build tools/__pycache__
