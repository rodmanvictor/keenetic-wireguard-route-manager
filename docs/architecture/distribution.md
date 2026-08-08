# Кроссплатформенные сборки

## Форматы

Проект публикует два нативных приложения для каждой платформы:

- `kwan` — самостоятельный консольный файл, собранный PyInstaller;
- Keenetic Route Manager — desktop-приложение, собранное Flet/Flutter.

Архив не требует заранее установленного Python. Установка через `pip` или `pipx` остаётся вариантом для разработчиков и пользователей, которым удобнее обновляться из исходников.

SQLite никогда не хранится внутри временного каталога нативной сборки. В
исходном checkout сохраняется совместимый `var/route-sync.sqlite3`, а
установленные приложения используют пользовательский каталог данных:

- Linux: `$XDG_DATA_HOME/keenetic-route-manager` или `~/.local/share/keenetic-route-manager`;
- macOS: `~/Library/Application Support/KeeneticRouteManager`;
- Windows: `%LOCALAPPDATA%\KeeneticRouteManager`.

## Нативная сборка

Windows, macOS и Linux собираются на собственных GitHub Actions runner. Flet и PyInstaller не используются для кросс-компиляции с одной ОС на другую.

Workflow `.github/workflows/release.yml` запускается вручную или тегом `v*`:

1. Устанавливает Python-зависимости.
2. На Linux устанавливает официальный desktop toolchain: Clang, CMake, Ninja и GTK3 headers.
3. Запускает offline-тесты.
4. Собирает standalone CLI через `scripts/build-cli.py`.
5. Собирает desktop через `flet build`.
6. Создаёт ZIP `keenetic-route-manager-<platform>.zip`.
7. Для тега прикладывает три архива к GitHub Release.

Локальная Linux-сборка:

```bash
sudo apt-get install -y clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev
python scripts/build-cli.py
./scripts/build-linux.sh
```

macOS-приложение должно собираться на macOS, Windows-приложение — на Windows. Подпись Apple Developer ID и Microsoft Authenticode в первой версии не настроена: операционная система может показать предупреждение о неизвестном издателе.

Первая macOS-сборка выпускается для x64 на официальном runner
`macos-26-intel`. На Apple Silicon она запускается через Rosetta 2; отдельный
нативный arm64-архив можно добавить после появления согласованного ARM-набора
Python/CFFI wheels в используемом Flet pipeline.
