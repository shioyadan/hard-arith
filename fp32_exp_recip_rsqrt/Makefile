# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PACKAGE_DIR := $(CURDIR)
RTL := $(PACKAGE_DIR)/fp32_exp_recip_rsqrt.sv
TB := $(PACKAGE_DIR)/test/tb_fp32_exp_recip_rsqrt.sv
REFERENCE := $(PACKAGE_DIR)/test/reference.c
SUPPORT_SUBNORMAL ?= 0
ifeq ($(filter $(SUPPORT_SUBNORMAL),0 1),)
$(error SUPPORT_SUBNORMALは0または1を指定してください)
endif
CONFIG_BUILD := $(PACKAGE_DIR)/build/subnormal-$(SUPPORT_SUBNORMAL)
BUILD_DIR := $(CONFIG_BUILD)/verilator
RANDOM_CYCLES ?= 200000
MONOTONIC_SAMPLES ?= 200000
EXHAUSTIVE_THREADS ?= 22
MONOTONIC_THREADS ?= 22
BUILD_JOBS ?= 8
PARAMETER_ARG := "-GSUPPORT_SUBNORMAL=1'b$(SUPPORT_SUBNORMAL)"
BASELINE_RTL ?=
CONFIGS_DIR := $(PACKAGE_DIR)/build/configs$(if $(BASELINE_RTL),-baseline,)
CONFIGS_EXE := $(CONFIGS_DIR)/VFP32ExpRecipRsqrtConfigs
CONFIGS_ARGS ?=

EXP_EXHAUSTIVE_DIR := $(CONFIG_BUILD)/verilator-exhaustive-exp
RECIP_EXHAUSTIVE_DIR := $(CONFIG_BUILD)/verilator-exhaustive-recip
RSQRT_EXHAUSTIVE_DIR := $(CONFIG_BUILD)/verilator-exhaustive-rsqrt
EXP_MONOTONIC_DIR := $(CONFIG_BUILD)/verilator-monotonic-exp
RECIP_MONOTONIC_DIR := $(CONFIG_BUILD)/verilator-monotonic-recip
RSQRT_MONOTONIC_DIR := $(CONFIG_BUILD)/verilator-monotonic-rsqrt

EXP_EXHAUSTIVE := $(EXP_EXHAUSTIVE_DIR)/VFP32ExpRecipRsqrt
RECIP_EXHAUSTIVE := $(RECIP_EXHAUSTIVE_DIR)/VFP32ExpRecipRsqrt
RSQRT_EXHAUSTIVE := $(RSQRT_EXHAUSTIVE_DIR)/VFP32ExpRecipRsqrt
EXP_MONOTONIC := $(EXP_MONOTONIC_DIR)/VFP32ExpRecipRsqrt
RECIP_MONOTONIC := $(RECIP_MONOTONIC_DIR)/VFP32ExpRecipRsqrt
RSQRT_MONOTONIC := $(RSQRT_MONOTONIC_DIR)/VFP32ExpRecipRsqrt

.PHONY: all lint test exhaustive exhaustive-active monotonic \
	constants constants-check clean test-configs

all: test

lint:
	verilator --lint-only --Wall --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32ExpRecipRsqrt $(PARAMETER_ARG) $(RTL)

test: lint
	@mkdir -p $(BUILD_DIR)
	verilator --binary --timing --Wno-fatal --Wno-DECLFILENAME \
		--Wno-UNUSEDSIGNAL --top-module FP32ExpRecipRsqrtTB \
		--Mdir $(BUILD_DIR) -GRANDOM_CYCLES=$(RANDOM_CYCLES) \
		-GMONOTONIC_SAMPLES=$(MONOTONIC_SAMPLES) \
		-GMAX_ALLOWED_ULP=1 -GCHECK_FAITHFUL=0 \
		$(PARAMETER_ARG) \
		$(RTL) $(TB) $(REFERENCE) \
		-CFLAGS '-std=gnu++17' -LDFLAGS '-lquadmath -lm'
	$(BUILD_DIR)/VFP32ExpRecipRsqrtTB

$(EXP_EXHAUSTIVE): $(RTL) $(PACKAGE_DIR)/test/exhaustive_exp.cpp Makefile
	@mkdir -p $(EXP_EXHAUSTIVE_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) -O3 $(PARAMETER_ARG) \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(EXP_EXHAUSTIVE_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive_exp.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp -DFP32_EXP_USE_QUADMATH -DSUPPORT_SUBNORMAL=$(SUPPORT_SUBNORMAL)' \
		-LDFLAGS '-fopenmp -lquadmath'

$(RECIP_EXHAUSTIVE): $(RTL) $(PACKAGE_DIR)/test/exhaustive_recip.cpp
	@mkdir -p $(RECIP_EXHAUSTIVE_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(RECIP_EXHAUSTIVE_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive_recip.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp'

$(RSQRT_EXHAUSTIVE): $(RTL) $(PACKAGE_DIR)/test/exhaustive_rsqrt.cpp
	@mkdir -p $(RSQRT_EXHAUSTIVE_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt --Mdir $(RSQRT_EXHAUSTIVE_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/exhaustive_rsqrt.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp'

ifeq ($(SUPPORT_SUBNORMAL),0)
ROOT_CHECKS := $(RECIP_EXHAUSTIVE) $(RSQRT_EXHAUSTIVE)
else
# ON側は新しい整数参照による二設定・根系全仮数／subnormal走査を使う。
ROOT_CHECKS := test-configs
endif

exhaustive-active: $(EXP_EXHAUSTIVE) $(ROOT_CHECKS)
	$(EXP_EXHAUSTIVE) --active --threads=$(EXHAUSTIVE_THREADS)
ifeq ($(SUPPORT_SUBNORMAL),0)
	$(RECIP_EXHAUSTIVE) --threads=$(EXHAUSTIVE_THREADS)
	$(RSQRT_EXHAUSTIVE) --threads=$(EXHAUSTIVE_THREADS)
endif

exhaustive: $(EXP_EXHAUSTIVE) $(ROOT_CHECKS)
	$(EXP_EXHAUSTIVE) --full --threads=$(EXHAUSTIVE_THREADS)
ifeq ($(SUPPORT_SUBNORMAL),0)
	$(RECIP_EXHAUSTIVE) --threads=$(EXHAUSTIVE_THREADS)
	$(RSQRT_EXHAUSTIVE) --threads=$(EXHAUSTIVE_THREADS)
endif

$(EXP_MONOTONIC): $(RTL) $(PACKAGE_DIR)/test/monotonic_exp.cpp Makefile
	@mkdir -p $(EXP_MONOTONIC_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt $(PARAMETER_ARG) --Mdir $(EXP_MONOTONIC_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/monotonic_exp.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp' \
		-LDFLAGS '-fopenmp'

$(RECIP_MONOTONIC): $(RTL) $(PACKAGE_DIR)/test/monotonic_recip.cpp Makefile
	@mkdir -p $(RECIP_MONOTONIC_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt $(PARAMETER_ARG) --Mdir $(RECIP_MONOTONIC_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/monotonic_recip.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20'

$(RSQRT_MONOTONIC): $(RTL) $(PACKAGE_DIR)/test/monotonic_rsqrt.cpp Makefile
	@mkdir -p $(RSQRT_MONOTONIC_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) -O3 \
		--Wno-fatal --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FP32ExpRecipRsqrt $(PARAMETER_ARG) --Mdir $(RSQRT_MONOTONIC_DIR) \
		$(RTL) $(PACKAGE_DIR)/test/monotonic_rsqrt.cpp \
		-CFLAGS '-O3 -march=native -std=gnu++20'

monotonic: $(EXP_MONOTONIC) $(RECIP_MONOTONIC) $(RSQRT_MONOTONIC)
	$(EXP_MONOTONIC) --threads=$(MONOTONIC_THREADS)
	$(RECIP_MONOTONIC)
	$(RSQRT_MONOTONIC)

$(CONFIGS_EXE): $(RTL) $(PACKAGE_DIR)/test/configs.sv $(PACKAGE_DIR)/test/configs.cpp $(REFERENCE) $(BASELINE_RTL) Makefile
	@mkdir -p $(CONFIGS_DIR)
	verilator --cc --exe --build --build-jobs $(BUILD_JOBS) -O3 \
		--Wno-DECLFILENAME --Wno-UNUSEDSIGNAL --top-module FP32ExpRecipRsqrtConfigs \
		--Mdir $(CONFIGS_DIR) $(RTL) $(PACKAGE_DIR)/test/configs.sv \
		$(if $(BASELINE_RTL),+define+COMPARE_BASELINE $(BASELINE_RTL),) \
		$(PACKAGE_DIR)/test/configs.cpp $(REFERENCE) \
		-CFLAGS '-O3 -march=native -std=gnu++20 -fopenmp $(if $(BASELINE_RTL),-DCOMPARE_BASELINE,)' \
		-LDFLAGS '-fopenmp -lquadmath -lm'

test-configs: $(CONFIGS_EXE)
	$(CONFIGS_EXE) $(CONFIGS_ARGS)

constants:
	python3 tools/gen_constants.py

constants-check:
	python3 tools/gen_constants.py --check

clean:
	rm -rf build tools/__pycache__
