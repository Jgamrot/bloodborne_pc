#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The shader pre-build catalog: which shader permutations and pipelines the game draws, merged
from players' pipeline caches (user/cache/CUSA03173), for every install to translate before
first sight (vk_shader_prebuild.h; run.py passes it as BB_SHADER_CATALOG).

Only the records are kept - a permutation's specialization and resource layout (.meta) and a
pipeline's state (.key) - in the current format. No SPIR-V and no game code: each install
translates the shaders from its own game files.

  shader_catalog.py <catalog folder> <cache folder> [<cache folder> ...] [--exclude <file>]
      --exclude: .meta names to leave out (bb-shader-prebuild --rejects: translations that do
      not match the game's own), so those shaders compile while playing as before
  shader_catalog.py --status <cache folder>     how much a play session has recorded
"""
from pathlib import Path
import shutil
import struct
import sys

# The versions the game writes (gpu/.../vk_pipeline_serialization.cpp): older records are left.
SHADER_META_VERSION = 8
PIPELINE_KEY_VERSION = 6


def current(path):
    want = SHADER_META_VERSION if path.suffix == '.meta' else PIPELINE_KEY_VERSION
    with path.open('rb') as file:
        head = file.read(4)
    return len(head) == 4 and struct.unpack('<I', head)[0] == want


def merge(catalog, caches, exclude=()):
    exclude = set(exclude)
    catalog = Path(catalog)
    catalog.mkdir(parents=True, exist_ok=True)
    added = 0
    for cache in caches:
        for record in sorted(Path(cache).iterdir()):
            if record.suffix not in ('.meta', '.key') or not current(record) or record.name in exclude:
                continue
            target = catalog / record.name
            if not target.exists():
                shutil.copyfile(record, target)
                added += 1
    total = sum(1 for p in catalog.iterdir() if p.suffix in ('.meta', '.key'))
    return added, total


def status(cache):
    """Current-format records in a cache: shader variants and pipelines seen so far."""
    cache = Path(cache)
    if not cache.is_dir():
        return 0, 0
    records = [p for p in cache.iterdir() if p.suffix in ('.meta', '.key') and current(p)]
    shaders = sum(p.suffix == '.meta' for p in records)
    return shaders, len(records) - shaders


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--status':
        shaders, pipelines = status(sys.argv[2])
        print(f'Recorded so far: {shaders} shader variants, {pipelines} pipelines.')
        return
    args = sys.argv[1:]
    exclude = ()
    if '--exclude' in args:
        at = args.index('--exclude')
        exclude = Path(args[at + 1]).read_text(encoding='utf-8').split()
        del args[at:at + 2]
    if len(args) < 2:
        sys.exit(__doc__)
    added, total = merge(args[0], args[1:], exclude)
    print(f'shader catalog: {added} records added, {total} in total')


if __name__ == '__main__':
    main()
