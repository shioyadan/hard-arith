# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
CXX ?= g++
PYTHON ?= python3
VARIANT ?= fp16
ifneq ($(VARIANT),fp16)
$(error 未知のVARIANTです: $(VARIANT))
endif
RTL_TOP := FP16BF16ExpRecipRsqrtStudy
FORMAT_MODE ?= 0
ifeq ($(filter $(FORMAT_MODE),0 1 2),)
$(error 未対応のFORMAT_MODEです: $(FORMAT_MODE))
endif
RTL_BUILD := build/$(VARIANT)/format-$(FORMAT_MODE)
.PHONY: test check
build/reference: reference.cpp
	mkdir -p build
	$(CXX) -std=c++17 -O2 $< -lm -o $@
build/reference.bin: build/reference
	$< $@
test: build/reference.bin
	$(PYTHON) -m unittest -v test_study.py
check: test rtl-check

.PHONY: rtl-generate rtl-check rtl-lint rtl-vectors rtl-test rtl-test-all
rtl-generate:
	$(PYTHON) gen_rtl.py
rtl-check:
	$(PYTHON) gen_rtl.py --check
rtl-lint: rtl-check
	verilator --lint-only -Wall -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME \
		--top-module $(RTL_TOP) -GFORMAT_MODE=$(FORMAT_MODE) rtl/$(VARIANT).sv
rtl-vectors: build/reference.bin
	$(PYTHON) gen_rtl.py --check --vectors
$(RTL_BUILD)/V$(RTL_TOP): rtl/$(VARIANT).sv rtl_test.cpp Makefile
	verilator --cc --exe --build -j 4 -Wall -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME \
		--top-module $(RTL_TOP) -GFORMAT_MODE=$(FORMAT_MODE) -CFLAGS -DFORMAT_MODE=$(FORMAT_MODE) \
		--Mdir $(RTL_BUILD) $< $(CURDIR)/rtl_test.cpp
rtl-test: rtl-lint rtl-vectors $(RTL_BUILD)/V$(RTL_TOP)
	$(RTL_BUILD)/V$(RTL_TOP) build/fp16.bin build/bf16.bin
rtl-test-all: test
	@for mode in 0 1 2; do $(MAKE) rtl-test FORMAT_MODE=$$mode || exit $$?; done
