#!/usr/bin/env python3
"""Build a sideloadable zip of the add-on into dist/."""
import os
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ID = os.path.basename(HERE)
EXCLUDE_DIRS = {'.git', 'dist', '__pycache__', '.ruff_cache', '.claude', 'tests'}
EXCLUDE_FILES = {'build.py', '.gitignore', 'README.md'}


def version():
    with open(os.path.join(HERE, 'addon.xml'), encoding='utf-8') as f:
        return re.search(r'<addon[^>]*\sversion="([^"]+)"', f.read()).group(1)


def main():
    out_dir = os.path.join(HERE, 'dist')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, '{}-{}.zip'.format(ADDON_ID, version()))
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(HERE):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for name in files:
                if name in EXCLUDE_FILES or name.endswith('.pyc'):
                    continue
                path = os.path.join(base, name)
                z.write(path, os.path.join(ADDON_ID, os.path.relpath(path, HERE)))
    print(out)


if __name__ == '__main__':
    main()
