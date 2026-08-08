# Сборки Windows, Linux и macOS

## Публикуемые файлы

Версия 0.3.2 публикуется для Windows 10/11, Linux и macOS:

- `packetech_<version>_amd64.deb` — Debian, Ubuntu и Linux Mint;
- `packetech-<version>-linux-x86_64.tar.gz` — переносимый Linux GUI и CLI;
- `SHA256SUMS-linux.txt` — контрольные суммы Linux-файлов;
- `packetech-<version>-windows-x86_64.zip` — переносимый Windows GUI и CLI;
- `SHA256SUMS-windows.txt` — контрольная сумма Windows-архива;
- `packetech-<version>-macos-arm64.dmg` — Apple Silicon;
- `packetech-<version>-macos-x86_64.dmg` — Intel Mac;
- отдельные SHA-256 для обеих macOS-архитектур.

## Linux-пакеты

Debian-пакет устанавливает:

- `/usr/lib/packetech/packetech-gui` — автономный Flet GUI;
- `/usr/bin/packetech-cli` — автономный CLI и исполнитель синхронизации;
- `/usr/lib/packetech/packetech-chrome-host` — локальный помощник расширения Chrome;
- `/usr/bin/packetech` — единый запуск GUI, CLI и TUI;
- `/usr/bin/paketych` — совместимый псевдоним старого имени;
- desktop entry и адаптивные иконки 16–512 px;
- пользовательский systemd-таймер `paketych-sync.timer`.

Python пользователю не нужен. GUI и CLI собираются PyInstaller на Linux; Flet
desktop runtime включается в GUI-файл.

## Windows-архив

Windows-сборка создается на нативном `windows-latest`. В архиве лежат:

- `PackeTech.exe` — автономный оконный интерфейс;
- `PackeTech-CLI.exe` — автономный CLI и исполнитель фоновой синхронизации;
- `PackeTech-Chrome-Host.exe` — локальный помощник расширения Chrome;
- `ПРОЧТИ МЕНЯ.txt` — короткий сценарий запуска.

После первого успешного подключения приложение создает задачу
`PackeTech route sync` с интервалом шесть часов. Папку нельзя переносить по
одному файлу: задача ссылается на абсолютный путь к `PackeTech-CLI.exe`.

Windows-файлы версии 0.3.2 не подписаны Authenticode. SmartScreen может
предупредить о неизвестном издателе.

## macOS DMG

Две macOS-сборки создаются на нативных GitHub-hosted runners: ARM64 на
`macos-26`, Intel x86-64 на `macos-26-intel`. Поддерживаемая команда
`flet build macos` формирует `PackeTech.app` для целевой архитектуры, а
`scripts/package-macos.py` добавляет внутрь standalone `packetech-cli` и
`packetech-chrome-host`, ставит ad-hoc
подпись и собирает DMG через `hdiutil`.

После первого подключения приложение регистрирует
`~/Library/LaunchAgents/ru.rodman.packetech.sync.plist`. LaunchAgent запускает
встроенный `packetech-cli sync` при загрузке и затем каждые 21 600 секунд. Пользователь
должен сначала перенести приложение в `/Applications`, иначе расписание будет
ссылаться на временно смонтированный DMG.

Apple Developer ID и нотаризация в версии 0.3.2 не используются. Первый запуск:
контекстное меню приложения → «Открыть».

## Изменяемые данные

Установленное приложение хранит изменяемые данные вне пакета:

- Linux-профиль: `$XDG_CONFIG_HOME/keenetic-route-manager/config.json` или
  `~/.config/keenetic-route-manager/config.json`;
- Linux SQLite: `$XDG_DATA_HOME/keenetic-route-manager/route-sync.sqlite3` или
  `~/.local/share/keenetic-route-manager/route-sync.sqlite3`;
- Windows-профиль: `%APPDATA%\KeeneticRouteManager\config.json`;
- Windows SQLite: `%LOCALAPPDATA%\KeeneticRouteManager\route-sync.sqlite3`;
- macOS профиль и SQLite: `~/Library/Application Support/KeeneticRouteManager/`.

Старое внутреннее имя каталогов сохраняется намеренно: переименование продукта
не должно обнулить настройки, пароль и базу доменов существующего пользователя.

## Локальная Linux-сборка

```bash
./scripts/build-linux.sh
```

Для поэтапной диагностики:

```bash
.venv-build/bin/python scripts/build-cli.py
.venv-build/bin/python scripts/build-desktop.py
.venv-build/bin/python scripts/package-linux.py
```

Windows-архив и macOS DMG собираются только на соответствующей ОС:

```text
python scripts/package-windows.py
python scripts/package-macos.py
```

## GitHub Actions

`.github/workflows/release.yml` запускается вручную или тегом `v*` на
`ubuntu-latest`, `windows-latest`, `macos-26` и `macos-26-intel`. Все matrix-job
выполняют offline-тесты. Linux и Windows собираются через PyInstaller, macOS —
штатной командой Flet поверх Flutter/Xcode. Теговый запуск прикладывает Linux,
Windows и обе macOS-архитектуры к одному GitHub Release.

## Проверка обновлений из приложения

GUI обращается к публичному `GET /repos/rodmanvictor/packetech/releases/latest`,
сравнивает числовую версию и выбирает файл по ОС и архитектуре. Скачанный пакет
сверяется с соответствующим `SHA256SUMS-*.txt` или SHA-256 digest из GitHub.
Приложение не заменяет собственный исполняемый файл: проверенный DEB, ZIP или
DMG передаётся штатному обработчику операционной системы.
