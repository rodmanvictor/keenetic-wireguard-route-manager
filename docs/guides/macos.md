# Установка в macOS

## Шаг 1. Выбрать сборку

- Mac на M1, M2, M3, M4 или M5: [Apple Silicon DMG](https://github.com/rodmanvictor/packetech/releases/download/v0.3.0/packetech-0.3.0-macos-arm64.dmg);
- Mac на Intel: [Intel DMG](https://github.com/rodmanvictor/packetech/releases/download/v0.3.0/packetech-0.3.0-macos-x86_64.dmg).

Архитектура указана в меню Apple → **«Об этом Mac»**.

## Шаг 2. Установить

Откройте DMG и перетащите `PackeTech.app` в `Applications`. Не запускайте
приложение из смонтированного DMG: фоновое обновление должно ссылаться на
постоянную копию.

## Шаг 3. Первый запуск

Сборка пока не нотарифицирована Apple. В `Applications` нажмите по PackeTech
правой кнопкой → **«Открыть»** → ещё раз **«Открыть»**.

Python, Homebrew и Терминал для графического режима не нужны.

## Командная строка

Терминальная команда находится внутри приложения:

```bash
/Applications/PackeTech.app/Contents/MacOS/packetech-cli status
/Applications/PackeTech.app/Contents/MacOS/packetech-cli tui
```

После первого подключения приложение создаёт LaunchAgent, который обновляет
домены каждые 6 часов.

## Где лежат данные

Профиль, пароль и база находятся в
`~/Library/Application Support/KeeneticRouteManager/`.

