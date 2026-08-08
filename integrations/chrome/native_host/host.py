#!/usr/bin/env python3
"""Compatibility entry point for source-checkout Chrome installations."""

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[3] / 'src'
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from keenetic_router.integrations.chrome_host import main, send_message


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        send_message({'ok': False, 'error': f'Помощник PackeTech остановлен: {error}'})
