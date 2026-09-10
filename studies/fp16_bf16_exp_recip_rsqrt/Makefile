# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
CXX ?= g++
PYTHON ?= python3
VARIANT ?= fp16
ifneq ($(VARIANT),fp16)
$(error 未知のVARIANTです: $(VARIANT))
endif
RTL_TOP := FP16BF16ExpRecipRsqrtStudy
.PHONY: test check
build/reference: reference.cpp
	mkdir -p build
	$(CXX) -std=c++17 -O2 $< -lm -o $@
build/reference.bin: build/reference
	$< $@
test: build/reference.bin
	$(PYTHON) -m unittest -v test_study.py
check: test rtl-check

.PHONY: rtl-generate rtl-check rtl-lint rtl-vectors rtl-test
rtl-generate:
	$(PYTHON) gen_rtl.py
rtl-check:
	$(PYTHON) gen_rtl.py --check
rtl-lint: rtl-check
	verilator --lint-only -Wall -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME --top-module $(RTL_TOP) rtl/$(VARIANT).sv
rtl-vectors: build/reference.bin
	$(PYTHON) gen_rtl.py --check --vectors
build/$(VARIANT)/V$(RTL_TOP): rtl/$(VARIANT).sv rtl_test.cpp
	verilator --cc --exe --build -j 4 -Wall -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME \
		--top-module $(RTL_TOP) --Mdir build/$(VARIANT) $< $(CURDIR)/rtl_test.cpp
rtl-test: rtl-lint rtl-vectors build/$(VARIANT)/V$(RTL_TOP)
	build/$(VARIANT)/V$(RTL_TOP) build/fp16.bin build/bf16.bin
