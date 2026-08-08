<p align="center">
  <img src="assets/branding/paketych-mascot.png" width="280" alt="PackeTech — 8-битный курьер интернет-пакетов">
</p>

<h1 align="center">PackeTech</h1>

<p align="center">
  <strong>Отправляю выбранные сайты через WireGuard. Остальной интернет не трогаю.</strong>
</p>

<p align="center">
  <img alt="Linux x86-64" src="https://img.shields.io/badge/Linux-x86--64-B8F34A?style=flat-square&logo=linux&logoColor=111">
  <img alt="Windows 10/11 x86-64" src="https://img.shields.io/badge/Windows-10%20%2F%2011-B8F34A?style=flat-square&logo=windows&logoColor=111">
  <img alt="macOS Intel/Apple Silicon" src="https://img.shields.io/badge/macOS-Intel%20%2F%20Apple%20Silicon-B8F34A?style=flat-square&logo=apple&logoColor=111">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-B8F34A?style=flat-square&logo=python&logoColor=111">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-B8F34A?style=flat-square">
</p>

Я — **PackeTech**. По-русски все так же Пакетыч: усатый курьер из эпохи
картриджей. Пока обычный VPN тащит
через себя весь дом, я работаю точечно: ChatGPT, YouTube, Discord или другой
выбранный сайт отправляю через WireGuard, а банки, магазины и локальные сервисы
оставляю на домашнем провайдере.

Никаких таблиц на 1000 IP вручную. Я подключаюсь к Keenetic, читаю названия
туннелей, обновляю DNS-маршруты каждые **6 часов** и помню, какой сайт откуда
появился.

> **Текущий уровень:** публичная beta для Windows 10/11, macOS и Linux x86-64.

## Как выглядит

<table>
  <tr>
    <td width="50%" valign="top">
      <strong>Сайты и маршруты</strong><br>
      Добавить домен, выбрать VPN и проверить, что маршрут включён.<br><br>
      <a href="docs/images/paketych-domains.png">
        <img src="docs/images/paketych-domains.png" alt="Главный экран PackeTech со списком сайтов и выбранным WireGuard-маршрутом">
      </a>
    </td>
    <td width="50%" valign="top">
      <strong>Настройка WireGuard</strong><br>
      Профили показаны человеческими именами из Keenetic, а не только wg0 и wg1.<br><br>
      <a href="docs/images/paketych-vpn.png">
        <img src="docs/images/paketych-vpn.png" alt="Управление WireGuard-профилями в PackeTech">
      </a>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <strong>Первое подключение</strong><br>
      Один раз вводите адрес Keenetic, логин и пароль — дальше PackeTech работает сам.<br><br>
      <a href="docs/images/paketych-connect.png">
        <img src="docs/images/paketych-connect.png" width="70%" alt="Первое подключение PackeTech к роутеру Keenetic">
      </a>
    </td>
  </tr>
</table>

## Миссия без сетевой магии

Обычная схема выглядит так:

```text
chatgpt.com ──► WireGuard «srv01» ──► интернет
банк.рф     ──► домашний провайдер ──► интернет
телевизор   ──► домашний провайдер ──► интернет
```

Я не являюсь VPN-сервисом и не продаю серверы. Мне нужен уже работающий
WireGuard-профиль: ваш сервер, конфиг провайдера или существующий туннель на
Keenetic.

## Мой арсенал

- подключаюсь к Keenetic по SSH;
- если SSH выключен, пробую включить его через Telnet и проверяю повторный вход;
- принимаю WireGuard `.conf` и QR-код;
- показываю человеческие названия VPN из Keenetic: например, `Mahteev` и `srv01`;
- принимаю домен или полный URL — сам убираю протокол, порт, путь и параметры;
- получаю favicon сайтов, а без сети показываю букву-заглушку;
- обновляю DNS и маршруты раз в 6 часов или по кнопке;
- не удаляю общий IP, пока он нужен хотя бы одному сайту;
- помню источник: Desktop, CLI, Chrome или каталог rucens;
- храню историю в SQLite и умею восстановить известные сайты из роутера.

## Уровень 1. Установить

Понадобятся:

- Keenetic с KeeneticOS;
- логин и пароль администратора роутера;
- Windows 10/11, 64-битный Linux или macOS на Apple Silicon/Intel;
- WireGuard-конфиг, QR-код или уже настроенный туннель.

### Windows 10 и 11

1. Откройте [последний выпуск](https://github.com/rodmanvictor/packetech/releases/latest).
2. Скачайте `packetech-0.3.0-windows-x86_64.zip`.
3. Нажмите на архив правой кнопкой и выберите **«Извлечь всё»**.
4. Откройте полученную папку и запустите **`PackeTech.exe`**.

Python, Git и командная строка не нужны. Не запускайте программу прямо внутри
ZIP и не переносите один EXE отдельно: лежащий рядом `kwan.exe` обновляет
маршруты каждые 6 часов.

Сборка пока не подписана платным сертификатом. Если SmartScreen покажет синее
окно «Система Windows защитила ваш компьютер», нажмите **«Подробнее»**, затем
**«Выполнить в любом случае»**. Проверить скачанный архив можно по файлу
`SHA256SUMS-windows.txt` из того же выпуска.

### Ubuntu, Debian и Linux Mint

1. Откройте [последний выпуск](https://github.com/rodmanvictor/packetech/releases/latest).
2. Скачайте `packetech_0.3.0_amd64.deb`.
3. Откройте файл двойным щелчком и нажмите «Установить».
4. Запустите **PackeTech** из меню приложений.

Если двойной щелчок не сработал:

```bash
sudo apt install ./packetech_0.3.0_amd64.deb
```

### Другой Linux x86-64

Скачайте `packetech-0.3.0-linux-x86_64.tar.gz`, распакуйте архив и запустите
файл `packetech`. Python и Flet устанавливать не нужно — всё уже внутри.

### macOS: Apple Silicon и Intel

1. Откройте [последний выпуск](https://github.com/rodmanvictor/packetech/releases/latest).
2. Для Mac на M1/M2/M3/M4/M5 скачайте `packetech-0.3.0-macos-arm64.dmg`.
3. Для Mac на Intel скачайте `packetech-0.3.0-macos-x86_64.dmg`.
4. Откройте DMG и перетащите `PackeTech.app` в `Applications`.
5. В `Applications` нажмите по приложению правой кнопкой и выберите **«Открыть»**.

Сборка подписана технической ad-hoc подписью, но пока не нотарифицирована Apple.
Поэтому обычный двойной щелчок при первом запуске может быть заблокирован.
Python, Homebrew и Терминал для работы приложения не нужны.

## Уровень 2. Подключить роутер

1. Оставьте `192.168.1.1`, если адрес роутера не меняли.
2. Введите логин администратора. Обычно это `admin`.
3. Введите пароль от панели Keenetic.
4. Нажмите **«Подключиться»**.

Я сначала проверю SSH. Если он недоступен, подключусь по Telnet, выполню
`service ssh`, сохраню конфигурацию и попробую SSH ещё раз. Если оба протокола
закрыты, покажу конкретную причину и не буду изображать бурную деятельность.

При первой установке локальная база пустая. Я прочитаю существующие
WireGuard-маршруты, уверенно распознанные сервисы положу в SQLite, а неизвестным
не стану выдумывать названия.

## Уровень 3. Добавить сайт

1. Вставьте адрес в поле **«Добавить сайт»**.
2. Нажмите зелёный `+` или Enter.
3. Если VPN несколько, выберите его по названию.

Можно вставить адрес прямо из браузера:

```text
https://chatgpt.com/share/example?ref=home
```

Я сохраню только `chatgpt.com`, получу его текущие IPv4-адреса и добавлю
маршруты на Keenetic. Через 6 часов проверю адреса снова.

## Настроить WireGuard

Откройте **«Настройка VPN»**. Здесь я показываю профили так, как они названы на
роутере. `wg1` и `Wireguard1` оставляю мелкой технической подписью.

В одном окне можно:

- добавить профиль из `.conf` или QR-кода;
- переименовать VPN;
- включить или отключить интерфейс;
- увидеть количество связанных сайтов;
- удалить неиспользуемый профиль.

Если через VPN идут активные сайты, удалить его не дам. Сначала отключите эти
сайты — потом доставайте гранату.

Закрытый и preshared-ключи передаю на роутер только по SSH. В журнал и SQLite
они не попадают.

## Chrome: добавить открытый сайт одной кнопкой

В репозитории есть расширение **«PackeTech · открыть сайт»**. Откройте сайт,
нажмите значок расширения — домен попадёт в общую базу с источником `Chrome` и
останется в шестичасовом обновлении.

Сейчас связка с Chrome поддерживается в Linux. Само приложение на Windows и
macOS работает независимо от расширения.

### Установка расширения в Linux

1. Скачайте и распакуйте [исходный код последнего выпуска](https://github.com/rodmanvictor/packetech/releases/latest).
2. Откройте в Chrome адрес `chrome://extensions`.
3. Включите справа сверху **«Режим разработчика»**.
4. Нажмите **«Загрузить распакованное расширение»**.
5. Выберите в распакованном проекте папку:

```text
integrations/chrome/extension
```

6. На карточке расширения скопируйте его 32-символьный ID.
7. В Терминале перейдите в распакованный проект и выполните:

```bash
python3 -m venv .venv-chrome
.venv-chrome/bin/python -m pip install -e .
./scripts/install-native-host-linux.sh EXTENSION_ID .venv-chrome/bin/python
```

Вместо `EXTENSION_ID` вставьте скопированный ID без кавычек. После этого вернитесь
на `chrome://extensions`, включите переключатель расширения и закрепите его
значок на панели Chrome.

Важно: круглая стрелка **Reload** перечитывает файлы, но не включает расширение
со статусом Off. Его переключатель включается отдельно.

## Командная строка для тех, кто любит чёрный экран

В `.deb` лежит самостоятельная команда `kwan`, а в Windows-архиве —
`kwan.exe`:

```bash
kwan setup
kwan status
kwan add chatgpt.com --tunnel wg1
kwan list
kwan sync
```

Полный список команд:

```bash
kwan --help
```

## Где лежат пароль и база

В Windows профиль роутера хранится здесь:

```text
%APPDATA%\KeeneticRouteManager\config.json
```

В Linux:

```text
~/.config/keenetic-route-manager/config.json
```

В Linux файл получает права `600`. Пароль хранится без шифрования: пользователь
с доступом к вашей учётной записи Windows или Linux сможет его прочитать. Не
отправляйте этот JSON другим людям и не добавляйте его в Git.

В Windows домены, IP, источники и история обновлений лежат в
`%LOCALAPPDATA%\KeeneticRouteManager\route-sync.sqlite3`. В Linux:

```text
~/.local/share/keenetic-route-manager/route-sync.sqlite3
```

## Боссы уровня

### Не подключается к роутеру

Проверьте 3 вещи: компьютер находится в домашней сети, `192.168.1.1` открывается
в браузере, а логин с паролем подходят для панели Keenetic.

### Сайт не открылся после добавления

Нажмите круглую стрелку в шапке. Затем проверьте в **«Настройка VPN»**, что
выбранный профиль включён и имеет доступ в интернет.

### Старые сайты не появились

Дождитесь первого чтения маршрутов. Я показываю только сервисы, которые удалось
сопоставить с проверенными списками. Неизвестный маршрут не превращаю в
«Наверное, YouTube».

### Проверить автообновление

На Windows откройте **Планировщик заданий** и найдите задачу
`PackeTech route sync`. На Linux:

```bash
systemctl --user status paketych-sync.timer
```

## Ограничения версии 0.3.0

- готовые сборки публикуются для Windows 10/11, Linux x86-64, macOS Apple Silicon и Intel;
- Windows-сборка пока не имеет цифровой подписи, поэтому возможен SmartScreen;
- macOS-сборки пока не нотарифицированы Apple, поэтому первый запуск делается через «Открыть»;
- Chrome-расширение пока подключается к локальному помощнику только в Linux;
- маршрутизация работает с IPv4;
- DNS и MTU из WireGuard-конфига не применяются автоматически;
- один профиль приложения управляет одним роутером;
- для работы нужен собственный WireGuard-сервер или VPN-провайдер;
- favicon загружаются через внешний сервис; без него остаётся буквенная иконка.

## Удалить игру, сохранить прогресс

В Windows удалите распакованную папку и задачу `PackeTech route sync` в
Планировщике заданий. В Linux:

```bash
sudo apt remove packetech
```

Настройки и SQLite останутся на месте. Чтобы удалить их без возможности
восстановления:

```bash
rm -r ~/.config/keenetic-route-manager ~/.local/share/keenetic-route-manager
```

## Запустить из исходников

```bash
git clone https://github.com/rodmanvictor/packetech.git
cd packetech
python3 -m venv .venv-build
.venv-build/bin/python -m pip install -r requirements-dev.txt -e .
npm run test:python
npm run docs:check
./scripts/build-linux.sh
```

Готовые файлы появятся в `dist/release/`:

- `packetech_0.3.0_amd64.deb`;
- `packetech-0.3.0-linux-x86_64.tar.gz`;
- `packetech-0.3.0-windows-x86_64.zip`;
- `packetech-0.3.0-macos-arm64.dmg` и `packetech-0.3.0-macos-x86_64.dmg`;
- контрольные суммы SHA-256 для каждой системы.

Архитектура и эксплуатационные заметки: [docs/README.md](docs/README.md).

---

Картридж вставлен. Пакеты собраны. Погнали. 〰️

Лицензия: [MIT](LICENSE).
