# Подсети Google

Утилиты для диапазонов Google находятся в `tools/google/`. Они используют официальный источник `https://www.gstatic.com/ipranges/goog.json` и добавляют IPv4-маршруты через выбранный WireGuard-интерфейс.

## Через терминальное меню

Запустите:

```bash
packetech tui
```

Затем выберите пункт добавления подсетей Google и нужный VPN по названию,
которое задано на роутере. Технический идентификатор `wgN` показан рядом.

## Через утилиты

Из корня проекта:

```bash
PYTHONPATH=src .venv-build/bin/python tools/google/add_routes.py wg1
PYTHONPATH=src .venv-build/bin/python tools/google/check_routes.py
```

Перед добавлением проверьте, что диапазоны нужны именно для Gemini или другого сервиса Google. Полный список Google может направить через VPN также YouTube, Gmail, Drive и прочий трафик Google.
