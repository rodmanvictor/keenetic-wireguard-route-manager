#!/usr/bin/env python3
"""Archive current-platform CLI and desktop artifacts for a GitHub release."""

import argparse
from pathlib import Path
import shutil


def main():
    """Create one ZIP without assuming platform-specific archive tools."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', required=True, choices=('linux', 'windows', 'macos'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    staging = root / 'build' / f'release-{args.platform}'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for folder in ('cli', 'desktop'):
        source = root / 'dist' / folder
        if source.exists():
            shutil.copytree(source, staging / folder)
    release_dir = root / 'dist' / 'release'
    release_dir.mkdir(parents=True, exist_ok=True)
    archive = shutil.make_archive(
        str(release_dir / f'keenetic-route-manager-{args.platform}'),
        'zip',
        staging,
    )
    print(archive)


if __name__ == '__main__':
    main()
