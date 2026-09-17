# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
PACKAGE := $(abspath ../..)
OUT := $(PACKAGE)/build/outer-opt
VARIANT ?= centered
THREADS ?= 8
JOBS ?= 4

.PHONY: generate constants-check test kernel-check equivalence equivalence-full
generate:
	python3 generate.py

constants-check:
	python3 generate.py --check
	$(MAKE) -C $(PACKAGE) constants-check

test:
	python3 generate.py --check
	$(MAKE) -C $(PACKAGE) test RTL=$(OUT)/$(VARIANT)/fp32_exp_recip_rsqrt.sv \
		BUILD_DIR=$(OUT)/$(VARIANT)/test

$(OUT)/kernel-obj/VKernelCheck: $(OUT)/kernel.sv check.cpp
	verilator --cc --exe --build -j $(JOBS) -O3 --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module KernelCheck --Mdir $(OUT)/kernel-obj $(OUT)/kernel.sv $(CURDIR)/check.cpp \
		-CFLAGS '-O3 -march=native -std=c++20 -fopenmp -DKERNEL_CHECK' -LDFLAGS '-fopenmp'

$(OUT)/full-obj/VFullCheck: $(OUT)/full.sv check.cpp
	verilator --cc --exe --build -j $(JOBS) -O3 --Wno-DECLFILENAME --Wno-UNUSEDSIGNAL \
		--top-module FullCheck --Mdir $(OUT)/full-obj $(OUT)/full.sv $(CURDIR)/check.cpp \
		-CFLAGS '-O3 -march=native -std=c++20 -fopenmp' -LDFLAGS '-fopenmp'

kernel-check: $(OUT)/kernel-obj/VKernelCheck
	$(OUT)/kernel-obj/VKernelCheck $(THREADS)

equivalence: $(OUT)/full-obj/VFullCheck
	$(OUT)/full-obj/VFullCheck $(THREADS)

equivalence-full: $(OUT)/full-obj/VFullCheck
	$(OUT)/full-obj/VFullCheck $(THREADS) --full
