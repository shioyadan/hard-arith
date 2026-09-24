#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""候補ごとに全64機能設定を検査し、別directoryへ証拠を保存する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from generate import UNIT, VARIANTS
from verify import command, digest


def run(sources, root, variant):
    base = root/variant
    base.mkdir(parents=True, exist_ok=False)
    source = sources/f'{variant}.sv'
    manifest = json.loads((sources/'manifest.json').read_text())
    assert digest(source) == manifest['sources_sha256'][source.name]
    files = [source, UNIT/'Makefile', UNIT/'test/function_enables.cpp',
             UNIT/'test/tb_function_enables.sv', UNIT/'test/reference.c', Path(__file__)]
    hashes = {str(path): digest(path) for path in files}
    text = command(['make', 'test-configs', f'RTL={source}', f'CONFIG_BUILD_DIR={base / "model"}'], base/'configs.log')
    assert text.count('PASS: configs=64 vectors=1625816 comparisons=104052224') == 1
    for path, sha in hashes.items():
        assert digest(Path(path)) == sha
    (base/'verification.json').write_text(json.dumps(dict(status='PASS', variant=variant,
        inputs_sha256=hashes, log_sha256=digest(base/'configs.log')), indent=2)+'\n')
    print('PASS: configs', variant, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        tasks = [executor.submit(run, args.sources.resolve(), args.output.resolve(), name) for name in args.variants]
        for task in tasks:
            task.result()


if __name__ == '__main__':
    main()
