# Windows/Linux-сборка и публикация

## Публикуемые файлы

Версия 0.3.0 публикуется для Windows 10/11 и Linux x86-64:

- `paketych_<version>_amd64.deb` — установочный пакет Debian, Ubuntu и Linux Mint;
- `paketych-<version>-linux-x86_64.tar.gz` — переносимый Linux GUI и CLI;
- `SHA256SUMS-linux.txt` — контрольные суммы Linux-файлов;
- `paketych-<version>-windows-x86_64.zip` — переносимый Windows GUI и CLI;
- `SHA256SUMS-windows.txt` — контрольная сумма Windows-архива.

macOS исключена из release workflow до завершения тестирования Windows- и
Linux-версий.

## Linux-пакеты

Debian-пакет устанавливает:

- `/usr/lib/paketych/paketych` — автономный Flet GUI;
- `/usr/bin/kwan` — автономный CLI;
- `/usr/bin/paketych` — системный запуск GUI;
- desktop entry и адаптивные иконки 16–512 px;
- пользовательский systemd-таймер `paketych-sync.timer`.

Python пользователю не нужен. GUI и CLI собираются PyInstaller на Linux; Flet
desktop runtime включается в GUI-файл. Системный Clang/GTK toolchain для этой
схемы сборки не требуется.

## Windows-архив

Windows-сборка создаётся на нативном `windows-latest`, а не кросс-компилируется
из Linux. В архиве лежат:

- `Пакетыч.exe` — автономный оконный интерфейс;
- `kwan.exe` — автономный CLI и исполнитель фоновой синхронизации;
- `ПРОЧТИ МЕНЯ.txt` — короткий сценарий запуска.

После первого успешного подключения приложение создаёт в Планировщике Windows
задачу `Paketych route sync` с интервалом шесть часов. Папку нельзя переносить
по одному файлу: задача ссылается на абсолютный путь к `kwan.exe`.

Windows-исполняемые файлы версии 0.3.0 не подписаны Authenticode. SmartScreen
может предупредить о неизвестном издателе; это фиксируется в пользовательском
README и не маскируется как ошибка сборки.

## Изменяемые данные

Установленное приложение хранит изменяемые данные вне пакета:

- Linux-профиль: `$XDG_CONFIG_HOME/keenetic-route-manager/config.json` или
  `~/.config/keenetic-route-manager/config.json`;
- Linux SQLite: `$XDG_DATA_HOME/keenetic-route-manager/route-sync.sqlite3` или
  `~/.local/share/keenetic-route-manager/route-sync.sqlite3`;
- Windows-профиль: `%APPDATA%\KeeneticRouteManager\config.json`;
- Windows SQLite: `%LOCALAPPDATA%\KeeneticRouteManager\route-sync.sqlite3`.

## Локальная Linux-сборка

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

Windows-архив собирается только на Windows после тех же двух PyInstaller-шагов:

```powershell
python scripts/package-windows.py
```

## GitHub Actions

`.github/workflows/release.yml` запускается вручную или тегом `v*` на
`ubuntu-latest` и `windows-latest`. Оба matrix-job выполняют offline-тесты и
собирают нативные GUI/CLI через PyInstaller. Linux-job создаёт `.deb` и
`.tar.gz`, Windows-job — `.zip`. Теговый запуск прикладывает артефакты обеих
систем к одному GitHub Release.
