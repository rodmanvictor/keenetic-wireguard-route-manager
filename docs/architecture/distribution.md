# Linux-сборка и публикация

## Публикуемые файлы

Версия 0.3.0 публикуется только для Linux x86-64:

- `paketych_<version>_amd64.deb` — установочный пакет для Debian, Ubuntu и Linux Mint;
- `paketych-<version>-linux-x86_64.tar.gz` — переносимый GUI и CLI;
- `SHA256SUMS` — контрольные суммы обоих файлов.

Windows и macOS намеренно исключены из release workflow до завершения
тестирования Linux-версии.

## Содержимое Debian-пакета

Пакет устанавливает:

- `/usr/lib/paketych/paketych` — автономный Flet GUI;
- `/usr/bin/kwan` — автономный CLI;
- `/usr/bin/paketych` — системный запуск GUI;
- desktop entry и адаптивные иконки 16–512 px;
- пользовательский systemd-таймер `paketych-sync.timer`.

Python пользователю не нужен. GUI и CLI собираются PyInstaller на Linux; Flet
desktop runtime включается в GUI-файл. Системный Clang/GTK toolchain для этой
схемы сборки не требуется.

Установленное приложение хранит изменяемые данные вне пакета:

- профиль: `$XDG_CONFIG_HOME/keenetic-route-manager/config.json` или
  `~/.config/keenetic-route-manager/config.json`;
- SQLite: `$XDG_DATA_HOME/keenetic-route-manager/route-sync.sqlite3` или
  `~/.local/share/keenetic-route-manager/route-sync.sqlite3`.

## Локальная сборка

```bash
./scripts/build-linux.sh
```

Скрипт создаёт виртуальное окружение при необходимости, собирает два
исполняемых файла, формирует `.deb` и переносимый архив, затем записывает
SHA-256.

Для поэтапной диагностики:

```bash
.venv-build/bin/python scripts/build-cli.py
.venv-build/bin/python scripts/build-desktop.py
.venv-build/bin/python scripts/package-linux.py
```

## GitHub Actions

`.github/workflows/release.yml` запускается вручную или тегом `v*` на
`ubuntu-latest`. Workflow выполняет offline-тесты, собирает Linux x86-64,
проверяет наличие артефактов и прикладывает их к GitHub Release.
