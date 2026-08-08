# Установка в Linux

## Ubuntu, Debian и Linux Mint

### Шаг 1. Скачать

Скачайте [DEB-пакет PackeTech](https://github.com/rodmanvictor/packetech/releases/download/v0.3.0/packetech_0.3.0_amd64.deb).

### Шаг 2. Установить

Откройте файл двойным щелчком и нажмите **«Установить»**. Если графический
установщик не сработал:

```bash
sudo apt install ./packetech_0.3.0_amd64.deb
```

### Шаг 3. Запустить

Откройте PackeTech из меню приложений или выполните:

```bash
packetech
```

## Переносимая версия

Для другого 64-битного Linux скачайте
[TAR.GZ](https://github.com/rodmanvictor/packetech/releases/download/v0.3.0/packetech-0.3.0-linux-x86_64.tar.gz),
распакуйте его и запустите `packetech`. Установка Python не нужна.

```bash
tar -xzf packetech-0.3.0-linux-x86_64.tar.gz
cd packetech
./packetech
```

## Терминал

В установленном DEB одна команда открывает все режимы:

```bash
packetech status
packetech add example.com --tunnel wg1
packetech tui
```

Все команды описаны в [руководстве по терминалу](terminal.md).

## Где лежат данные

- профиль и пароль: `~/.config/keenetic-route-manager/config.json`;
- домены и история: `~/.local/share/keenetic-route-manager/route-sync.sqlite3`.

Каталог профиля получает права `700`, файл — `600`. Пароль записан без
дополнительного шифрования и доступен программам текущего пользователя Linux.

