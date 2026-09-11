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
SUPPORT_SUBNORMAL ?= 1
ifeq ($(filter $(SUPPORT_SUBNORMAL),0 1),)
$(error 未対応のSUPPORT_SUBNORMALです: $(SUPPORT_SUBNORMAL))
endif
ifeq ($(filter $(FORMAT_MODE),0 1 2),)
$(error 未対応のFORMAT_MODEです: $(FORMAT_MODE))
endif
VECTOR_BUILD := build/subnormal-$(SUPPORT_SUBNORMAL)
RTL_BUILD := $(VECTOR_BUILD)/format-$(FORMAT_MODE)
.PHONY: model-test test check
build/reference: reference.cpp
	mkdir -p build
	$(CXX) -std=c++17 -O2 $< -lm -o $@
build/reference.bin: build/reference
	$< $@
build/reference-subnormal.bin: build/reference
	$< $@ 1
model-test: build/reference.bin build/reference-subnormal.bin
	$(PYTHON) -m unittest -v test_study.py
test: model-test rtl-test
check: model-test rtl-check

.PHONY: rtl-generate rtl-check rtl-lint rtl-vectors rtl-test rtl-test-all
rtl-generate:
	$(PYTHON) gen_rtl.py
rtl-check:
	$(PYTHON) gen_rtl.py --check
rtl-lint: rtl-check
	verilator --lint-only -Wall -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME \
		--top-module $(RTL_TOP) -GFORMAT_MODE=$(FORMAT_MODE) "-GSUPPORT_SUBNORMAL=1'b$(SUPPORT_SUBNORMAL)" rtl/$(VARIANT).sv
rtl-vectors: build/reference.bin build/reference-subnormal.bin
	$(PYTHON) gen_rtl.py --check --vectors --support-subnormal $(SUPPORT_SUBNORMAL)
$(RTL_BUILD)/V$(RTL_TOP): rtl/$(VARIANT).sv rtl_test.cpp Makefile
	verilator --cc --exe --build -j 4 -Wall -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME \
		--top-module $(RTL_TOP) -GFORMAT_MODE=$(FORMAT_MODE) "-GSUPPORT_SUBNORMAL=1'b$(SUPPORT_SUBNORMAL)" \
		-CFLAGS '-DFORMAT_MODE=$(FORMAT_MODE) -DSUPPORT_SUBNORMAL=$(SUPPORT_SUBNORMAL)' \
		--Mdir $(RTL_BUILD) $< $(CURDIR)/rtl_test.cpp
rtl-test: rtl-lint rtl-vectors $(RTL_BUILD)/V$(RTL_TOP)
	$(RTL_BUILD)/V$(RTL_TOP) $(VECTOR_BUILD)/fp16.bin $(VECTOR_BUILD)/bf16.bin
rtl-test-all: model-test
	@for subnormal in 0 1; do for mode in 0 1 2; do \
		$(MAKE) rtl-test FORMAT_MODE=$$mode SUPPORT_SUBNORMAL=$$subnormal || exit $$?; done; done

# リポジトリ直下の共通targetからも検証できるようにする。
.PHONY: lint constants-check exhaustive monotonic clean
lint: rtl-lint
constants-check: rtl-check
exhaustive: rtl-test-all
monotonic: model-test
clean:
	rm -rf build
