#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Create a deterministic offline legacy add-on ZIP for Blender 4.2+."""

import argparse
import hashlib
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    addons = repo / 'scripts/addons_core'
    target = args.output / 'VioletBlender-pmx-addon.zip'
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for package in ('mmd_tools', 'violet_pmx'):
            # Sort normalized strings so Windows and POSIX use the same ordering.
            for path in sorted((addons / package).rglob('*'),
                               key=lambda path: path.relative_to(addons).as_posix()):
                if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                    continue
                info = zipfile.ZipInfo(path.relative_to(addons).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compresslevel=9)
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(f'{checksum}  {target.name}\n', encoding='utf-8')
    print(f'{target}: {target.stat().st_size} bytes, SHA-256 {checksum}')


if __name__ == '__main__':
    main()
