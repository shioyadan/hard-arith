# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PACKAGE_DIR := $(CURDIR)
RTL := $(PACKAGE_DIR)/fp32_exp_recip_rsqrt.sv
TB := $(PACKAGE_DIR)/test/tb_fp32_exp_recip_rsqrt.sv
REFERENCE := $(PACKAGE_DIR)/test/reference.c
BUILD_DIR := $(PACKAGE_DIR)/build/verilator
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000
EXHAUSTIVE_THREADS ?= 22
MONOTONIC_THREADS ?= 22

EXP_EXHAUSTIVE_DIR := $(PACKAGE_DIR)/build/verilator-exhaustive-exp
RECIP_EXHAUSTIVE_DIR := $(PACKAGE_DIR)/build/verilator-exhaustive-recip
RSQRT_EXHAUSTIVE_DIR := $(PACKAGE_DIR)/build/verilator-exhaustive-rsqrt
EXP_MONOTONIC_DIR := $(PACKAGE_DIR)/build/verilator-monotonic-exp
RECIP_MONOTONIC_DIR := $(PACKAGE_DIR)/build/verilator-monotonic-recip
RSQRT_MONOTONIC_DIR := $(PACKAGE_DIR)/build/verilator-monotonic-rsqrt

EXP_EXHAUSTIVE := $(EXP_EXHAUSTIVE_DIR)/VFP32ExpRecipRsqrt
RECIP_EXHAUSTIVE := $(RECIP_EXHAUSTIVE_DIR)/VFP32ExpRecipRsqrt
RSQRT_EXHAUSTIVE := $(RSQRT_EXHAUSTIVE_DIR)/VFP32ExpRecipRsqrt
EXP_MONOTONIC := $(EXP_MONOTONIC_DIR)/VFP32ExpRecipRsqrt
RECIP_MONOTONIC := $(RECIP_MONOTONIC_DIR)/VFP32ExpRecipRsqrt
RSQRT_MONOTONIC := $(RSQRT_MONOTONIC_DIR)/VFP32ExpRecipRsqrt

.PHONY: all lint test exhaustive exhaustive-active monotonic \
	constants constants-check clean

all: test

lint:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32ExpRecipRsqrt $(RTL)

test: lint
	@mkdir -p $(BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32ExpRecipRsqrtTB \
		--Mdir $(BUILD_DIR) -GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		-GMAX_ALLOWED_ULP=1 -GCHECK_FAITHFUL=0 \
		-GREFERENCE_SUBNORMAL=0 \
		$(RTL) $(TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17' -LDFLAGS '-lquadmath -lm'
	$(BUILD_DIR)/VFP32ExpRecipRsqrtTB

$(EXP_EXHAUSTIVE): $(RTL) $(PACKAGE_DIR)/test/exhaustive_exp.cpp
	@mkdir -p $(EXP_EXHAUSTIVE_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(EXP_EXHAUSTIVE_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive_exp.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp -DFP32_EXP_USE_QUADMATH' \
		-LDFLAGS '-fopenmp -lquadmath'

$(RECIP_EXHAUSTIVE): $(RTL) $(PACKAGE_DIR)/test/exhaustive_recip.cpp
	@mkdir -p $(RECIP_EXHAUSTIVE_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(RECIP_EXHAUSTIVE_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive_recip.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp'

$(RSQRT_EXHAUSTIVE): $(RTL) $(PACKAGE_DIR)/test/exhaustive_rsqrt.cpp
	@mkdir -p $(RSQRT_EXHAUSTIVE_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(RSQRT_EXHAUSTIVE_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive_rsqrt.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp'

exhaustive-active: $(EXP_EXHAUSTIVE) $(RECIP_EXHAUSTIVE) $(RSQRT_EXHAUSTIVE)
	$(EXP_EXHAUSTIVE) --active --threads=$(EXHAUSTIVE_THREADS)
	$(RECIP_EXHAUSTIVE) --threads=$(EXHAUSTIVE_THREADS)
	$(RSQRT_EXHAUSTIVE) --threads=$(EXHAUSTIVE_THREADS)

exhaustive: $(EXP_EXHAUSTIVE) $(RECIP_EXHAUSTIVE) $(RSQRT_EXHAUSTIVE)
	$(EXP_EXHAUSTIVE) --full --threads=$(EXHAUSTIVE_THREADS)
	$(RECIP_EXHAUSTIVE) --threads=$(EXHAUSTIVE_THREADS)
	$(RSQRT_EXHAUSTIVE) --threads=$(EXHAUSTIVE_THREADS)

$(EXP_MONOTONIC): $(RTL) $(PACKAGE_DIR)/test/monotonic_exp.cpp
	@mkdir -p $(EXP_MONOTONIC_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(EXP_MONOTONIC_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/monotonic_exp.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp'

$(RECIP_MONOTONIC): $(RTL) $(PACKAGE_DIR)/test/monotonic_recip.cpp
	@mkdir -p $(RECIP_MONOTONIC_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(RECIP_MONOTONIC_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/monotonic_recip.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20'

$(RSQRT_MONOTONIC): $(RTL) $(PACKAGE_DIR)/test/monotonic_rsqrt.cpp
	@mkdir -p $(RSQRT_MONOTONIC_DIR)
	verilator --cc --exe --build --build-jobs 0 -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(RSQRT_MONOTONIC_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/monotonic_rsqrt.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20'

monotonic: $(EXP_MONOTONIC) $(RECIP_MONOTONIC) $(RSQRT_MONOTONIC)
	$(EXP_MONOTONIC) --threads=$(MONOTONIC_THREADS)
	$(RECIP_MONOTONIC)
	$(RSQRT_MONOTONIC)

constants:
	python3 tools/gen_constants.py

constants-check:
	python3 tools/gen_constants.py --check

clean:
	rm -rf build tools/__pycache__
