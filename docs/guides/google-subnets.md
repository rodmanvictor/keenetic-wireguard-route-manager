# Подсети Google

Утилиты для диапазонов Google находятся в `tools/google/`. Они используют официальный источник `https://www.gstatic.com/ipranges/goog.json` и добавляют IPv4-маршруты через выбранный WireGuard-интерфейс.

## Через терминальное меню

Запустите:

```bash
kwtui
```

Затем выберите пункт добавления подсетей Google и нужный туннель. Для текущей домашней схемы выбирайте `wg1` / `Wireguard1 (srv01)`.

## Через утилиты

Из корня проекта:

```bash
PYTHONPATH=src .venv-build/bin/python tools/google/add_routes.py wg1
PYTHONPATH=src .venv-build/bin/python tools/google/check_routes.py
```

Перед добавлением проверьте, что диапазоны нужны именно для Gemini или другого сервиса Google. Полный список Google может направить через VPN также YouTube, Gmail, Drive и прочий трафик Google.
