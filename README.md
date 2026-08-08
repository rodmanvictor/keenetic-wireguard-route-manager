<p align="center">
  <img src="assets/branding/paketych-mascot.png" width="260" alt="PackeTech — 8-битный курьер интернет-пакетов">
</p>

<h1 align="center">PackeTech</h1>

<p align="center">
  <strong>Отправляет выбранные сайты через WireGuard. Остальной интернет не трогает.</strong>
</p>

<p align="center">
  <img alt="Windows 10 и 11" src="https://img.shields.io/badge/Windows-10%20%2F%2011-B8F34A?style=flat-square&logo=windows&logoColor=111">
  <img alt="macOS" src="https://img.shields.io/badge/macOS-Intel%20%2F%20Apple%20Silicon-B8F34A?style=flat-square&logo=apple&logoColor=111">
  <img alt="Linux x86-64" src="https://img.shields.io/badge/Linux-x86--64-B8F34A?style=flat-square&logo=linux&logoColor=111">
  <img alt="MIT License" src="https://img.shields.io/badge/license-MIT-B8F34A?style=flat-square">
</p>

Я сделал PackeTech для дома: добавил сайт — и Keenetic отправляет его через
нужный WireGuard-профиль. Банки, магазины и остальные сайты продолжают работать
через обычного провайдера.

Программа сама подключается к роутеру, запоминает домены, обновляет IPv4- и
IPv6-маршруты каждые 6 часов и не требует вручную вести таблицу IP-адресов.

## Скачать

**Актуальная версия: 0.3.2** · выпуски публикуются для Windows, Linux и macOS.

| Система | Готовый файл | Подробная инструкция |
|---|---|---|
| 🪟 **Windows 10/11** | [Скачать ZIP](https://github.com/rodmanvictor/packetech/releases/download/v0.3.2/packetech-0.3.2-windows-x86_64.zip) | [Установка в Windows](docs/guides/windows.md) |
| 🐧 **Ubuntu, Debian, Mint** | [Скачать DEB](https://github.com/rodmanvictor/packetech/releases/download/v0.3.2/packetech_0.3.2_amd64.deb) | [Установка в Linux](docs/guides/linux.md) |
| 🐧 **Другой Linux x86-64** | [Скачать TAR.GZ](https://github.com/rodmanvictor/packetech/releases/download/v0.3.2/packetech-0.3.2-linux-x86_64.tar.gz) | [Переносимая версия](docs/guides/linux.md#переносимая-версия) |
| 🍎 **Mac с Apple Silicon** | [Скачать DMG](https://github.com/rodmanvictor/packetech/releases/download/v0.3.2/packetech-0.3.2-macos-arm64.dmg) | [Установка в macOS](docs/guides/macos.md) |
| 🍎 **Mac с Intel** | [Скачать DMG](https://github.com/rodmanvictor/packetech/releases/download/v0.3.2/packetech-0.3.2-macos-x86_64.dmg) | [Установка в macOS](docs/guides/macos.md) |

Все файлы выпуска: [GitHub Releases](https://github.com/rodmanvictor/packetech/releases/latest).

## Три шага

### Шаг 1. Установить

Скачайте сборку для своей системы и запустите PackeTech. Python, Git и знания
сетевого инженера не нужны.

### Шаг 2. Подключить роутер

Введите адрес Keenetic, логин и пароль администратора. Программа проверит SSH,
а если он выключен — попробует включить его через Telnet.

### Шаг 3. Добавить сайт

Вставьте домен или полный адрес страницы, выберите VPN и нажмите `+`. PackeTech
сам уберёт `https://`, путь и параметры, найдёт IP-адреса и создаст маршруты.

## Как выглядит

<table>
  <tr>
    <td width="50%"><a href="docs/images/paketych-domains.png"><img src="docs/images/paketych-domains.png" alt="Список сайтов в PackeTech"></a></td>
    <td width="50%"><a href="docs/images/paketych-vpn.png"><img src="docs/images/paketych-vpn.png" alt="Настройка WireGuard в PackeTech"></a></td>
  </tr>
  <tr>
    <td align="center"><strong>Сайты и маршруты</strong></td>
    <td align="center"><strong>Настройка WireGuard</strong></td>
  </tr>
</table>

Первое подключение:

<p align="center">
  <a href="docs/images/paketych-connect.png"><img src="docs/images/paketych-connect.png" width="72%" alt="Подключение PackeTech к Keenetic"></a>
</p>

## Терминал тоже есть

Один бренд — три режима:

```bash
packetech                 # графическое приложение
packetech status          # обычная команда
packetech tui             # интерактивное терминальное меню
```

<table>
  <tr>
    <td width="55%"><a href="docs/images/packetech-cli.png"><img src="docs/images/packetech-cli.png" alt="PackeTech CLI"></a></td>
    <td width="45%"><a href="docs/images/packetech-tui.png"><img src="docs/images/packetech-tui.png" alt="PackeTech TUI"></a></td>
  </tr>
  <tr>
    <td align="center"><strong>CLI для команд и скриптов</strong></td>
    <td align="center"><strong>TUI для работы без мышки</strong></td>
  </tr>
</table>

[Команды, установка через Python и примеры →](docs/guides/terminal.md)

## Что умеет

- добавлять домен или полный URL;
- направлять каждый сайт через выбранный WireGuard-профиль;
- показывать названия VPN, заданные на роутере;
- сообщать о новой версии, скачивать подходящую сборку и проверять SHA-256;
- работать с DNS A/AAAA и маршрутами IPv4 `/32` и IPv6 `/128`;
- обновлять адреса автоматически или по кнопке;
- импортировать WireGuard из `.conf` и QR-кода;
- сохранять общие IP, пока они нужны хотя бы одному сайту;
- устанавливать расширение Chrome прямо из PackeTech и добавлять текущий сайт одной кнопкой;
- работать через графическое окно, CLI и TUI.

PackeTech пока управляет роутерами Keenetic. Сам VPN-сервис в программу не
входит: нужен готовый WireGuard-конфиг, свой сервер или профиль провайдера.

## Инструкции

- [Windows](docs/guides/windows.md)
- [Linux](docs/guides/linux.md)
- [macOS](docs/guides/macos.md)
- [Командная строка и TUI](docs/guides/terminal.md)
- [Расширение Chrome](docs/guides/chrome-extension.md)
- [Первое подключение и WireGuard](docs/guides/first-run.md)
- [Архитектура и разработка](docs/README.md)

## Разработка

```bash
git clone https://github.com/rodmanvictor/packetech.git
cd packetech
python3 -m venv .venv-build
.venv-build/bin/python -m pip install -r requirements-dev.txt -e .
npm run test:python
npm run docs:check
```

Автор: **Victor Rodin**. Лицензия: [MIT](LICENSE).

Картридж вставлен. Пакеты собраны. Погнали. 〰️
