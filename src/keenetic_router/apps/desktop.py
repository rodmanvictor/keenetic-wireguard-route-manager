#!/usr/bin/env python3
"""Cross-platform Flet application for onboarding and route management.

The first screen authenticates to one router, enables SSH through Telnet when
possible, and stores the password in the current user's JSON configuration.
The dashboard remains a thin layer over the shared registry, synchronizer, and
WireGuard importer.
"""

import asyncio
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import flet as ft

from keenetic_router.core.onboarding import (
    bootstrap_router,
    inspect_components,
    install_components,
)
from keenetic_router.core.profiles import RouterProfile, load_profile, save_profile
from keenetic_router.core.router import clear_runtime_connection, create_router_client
from keenetic_router.core.scheduler import enable_background_sync
from keenetic_router.core.wireguard import (
    delete_wireguard_tunnel,
    import_wireguard_profile,
    load_wireguard_file,
    load_wireguard_qr,
    rename_wireguard_tunnel,
    set_wireguard_tunnel_enabled,
)
from keenetic_router.services.registry import (
    add_managed_domain,
    domain_addresses,
    domain_inventory_routes,
    list_managed_domains,
    normalize_domain,
    recent_runs,
    remove_managed_domain,
    source_label,
    split_sources,
)
from keenetic_router.services.sync import sync_domains
from keenetic_router.services.cleanup import purge_domain_routes
from keenetic_router.services.catalog import reconcile_inventory_domains
from keenetic_router.services.inventory import import_current_inventory
from keenetic_router.services.favicons import favicon_url
from keenetic_router.integrations.chrome_installer import (
    detect_chrome,
    inspect_chrome_extension,
    open_chrome_extensions,
    prepare_chrome_extension,
    reveal_extension_directory,
)
from keenetic_router import __version__
from keenetic_router.services.updates import (
    UpdateInfo,
    download_update,
    fetch_latest_release,
    installation_hint,
    open_downloaded_update,
)


BG = '#0B0E0C'
PANEL = '#151A16'
PANEL_ACTIVE = '#20281E'
LINE = '#2B342C'
TEXT = '#F2F6EE'
MUTED = '#899487'
ACID = '#B8F34A'
DANGER = '#FF786E'
BRAND_ICON = files('keenetic_router').joinpath('assets/paketych-icon-small.png').read_bytes()
BRAND_MASCOT = files('keenetic_router').joinpath('assets/paketych-mascot.png').read_bytes()


class RouteDesktop:
    """Render and coordinate the small desktop administration interface.

    Args:
        page: Active Flet page supplied by the desktop runtime.

    Side effects:
        Reads and updates the shared SQLite registry. Explicit user actions may
        connect to Keenetic through the shared SSH synchronizer.
    """

    def __init__(self, page: ft.Page):
        self.page = page
        self.profile = load_profile()
        self.password = self.profile.password
        self.report = None
        self.tunnels = {}
        self.tunnel_labels = {}
        self.tunnel_statuses = {}
        self.component_states = {}
        self.chrome_installation = None
        self.update_info: UpdateInfo | None = None
        self.update_button = None
        self.update_check_started = False
        self.rows = []
        self.selected_id = None
        self.busy = False
        self.initial_status = 'Локальная база готова'

        self.quick_domain = ft.TextField(
            hint_text='Добавить сайт',
            prefix_icon=ft.Icons.LANGUAGE,
            border_radius=14,
            border_color=LINE,
            focused_border_color=ACID,
            bgcolor=PANEL,
            color=TEXT,
            dense=True,
            height=48,
            on_submit=self.quick_add_site,
            expand=True,
        )
        self.domain_list = ft.ListView(expand=True, spacing=8, padding=0)
        self.domain_count_text = ft.Text('0 добавлено', color=MUTED, size=10)
        self.detail = ft.Column(expand=True, spacing=12)
        self.status_text = ft.Text('Локальная база', color=MUTED, size=12)
        self.sync_button = None
        self.root = ft.Column(expand=True, spacing=0)
        self.file_picker = ft.FilePicker()

    def configure_page(self):
        """Apply the desktop theme and render the first-run connection screen."""
        self.page.title = 'PackeTech · сайты через VPN'
        self.page.bgcolor = BG
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 0
        self.page.window.width = 1080
        self.page.window.height = 800
        self.page.window.min_width = 900
        self.page.window.min_height = 620
        self.page.services.append(self.file_picker)
        self.page.add(self.root)
        self.render_login()

    def render_login(self, error=None):
        """Render a stable two-column connection screen without layout jumps."""
        self.root.controls.clear()
        host = ft.TextField(
            label='Адрес роутера',
            value=self.profile.host,
            hint_text='192.168.1.1',
            prefix_icon=ft.Icons.ROUTER,
            border_color=LINE,
            focused_border_color=ACID,
        )
        user = ft.TextField(
            label='Логин',
            value=self.profile.user,
            prefix_icon=ft.Icons.PERSON_OUTLINE,
            border_color=LINE,
            focused_border_color=ACID,
        )
        password = ft.TextField(
            label='Пароль',
            value=self.profile.password,
            password=True,
            can_reveal_password=True,
            prefix_icon=ft.Icons.KEY,
            border_color=LINE,
            focused_border_color=ACID,
            on_submit=lambda event: self.page.run_task(connect, event),
        )
        auto_ssh = ft.Checkbox(
            label='Автоматически включить SSH через Telnet',
            value=True,
            active_color=ACID,
        )
        login_status = ft.Text(error or '', color=DANGER if error else MUTED, size=12)

        def button_content(label, *, loading=False):
            """Return fixed-height button contents for idle or loading state."""
            leading = (
                ft.ProgressRing(width=18, height=18, stroke_width=2, color=BG)
                if loading
                else ft.Icon(ft.Icons.LINK, size=18, color=BG)
            )
            return ft.Row(
                tight=True,
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[leading, ft.Text(label, weight=ft.FontWeight.BOLD)],
            )

        def set_connecting(label):
            """Lock the submit button and replace its contents in place."""
            connect_button.disabled = True
            connect_button.content = button_content(label, loading=True)
            login_status.color = MUTED
            login_status.value = ''
            self.page.update()

        def reset_connect_button():
            """Restore the idle submit state after a failed connection."""
            connect_button.disabled = False
            connect_button.content = button_content('Подключиться')

        async def connect(_event=None):
            set_connecting('Проверяю SSH…')
            try:
                profile = RouterProfile(
                    name=self.profile.name,
                    host=host.value or '',
                    user=user.value or '',
                    ssh_port=self.profile.ssh_port,
                    telnet_port=self.profile.telnet_port,
                    password=password.value or '',
                ).validate()
                report = await asyncio.to_thread(
                    bootstrap_router,
                    profile,
                    password.value or '',
                    auto_enable_ssh=bool(auto_ssh.value),
                )
                selected = replace(
                    profile,
                    preferred_transport=report.transport or 'auto',
                    password=password.value or '',
                )
                save_profile(selected)
                self.profile = selected
                self.password = password.value or ''
                self.report = report
                self.tunnels = dict(report.tunnels)
                self.tunnel_labels = dict(report.tunnel_labels)
                self.tunnel_statuses = dict(report.tunnel_statuses)
                set_connecting('Читаю маршруты…')
                self.component_states = await asyncio.to_thread(self._inspect_components)
                try:
                    inventory_note = await asyncio.to_thread(self._bootstrap_inventory_if_needed)
                except Exception as exception:
                    inventory_note = f'Подключено, но маршруты не импортированы: {exception}'
                if inventory_note:
                    self.initial_status = inventory_note
                timer = await asyncio.to_thread(enable_background_sync)
                if timer.enabled:
                    self.initial_status = f'{self.initial_status} · автообновление каждые 6 ч'
            except Exception as exception:
                reset_connect_button()
                login_status.color = DANGER
                login_status.value = str(exception)
                self.page.update()
                return
            self.render_dashboard()
            self.reload_data()
            if not self.update_check_started:
                self.update_check_started = True
                self.page.run_task(self.check_for_updates)

        connect_button = ft.Button(
            content=button_content('Подключиться'),
            bgcolor=ACID,
            color=BG,
            height=52,
            width=430,
            elevation=0,
            on_click=connect,
        )
        hero = ft.Container(
            width=460,
            bgcolor='#101510',
            padding=48,
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                tight=True,
                spacing=14,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Image(
                        src=BRAND_MASCOT,
                        width=300,
                        height=300,
                        fit=ft.BoxFit.CONTAIN,
                        filter_quality=ft.FilterQuality.NONE,
                    ),
                    ft.Text('PACKETECH', color=ACID, size=13, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        'Доставляет сайты\nчерез нужный VPN',
                        color=TEXT,
                        size=28,
                        weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        'Остальной интернет продолжает работать\nчерез домашнего провайдера.',
                        color=MUTED,
                        size=13,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
            ),
        )
        form = ft.Container(
            expand=True,
            bgcolor=BG,
            padding=52,
            alignment=ft.Alignment.CENTER,
            content=ft.Container(
                width=430,
                content=ft.Column(
                    tight=True,
                    spacing=16,
                    controls=[
                        ft.Text('Подключение к роутеру', color=TEXT, size=30, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            'Введите данные администратора Keenetic. Это нужно один раз.',
                            color=MUTED,
                            size=13,
                        ),
                        ft.Container(height=8),
                        host,
                        user,
                        password,
                        auto_ssh,
                        ft.Container(height=36, alignment=ft.Alignment.CENTER_LEFT, content=login_status),
                        connect_button,
                        ft.Row(
                            spacing=8,
                            controls=[
                                ft.Icon(ft.Icons.LOCK_OUTLINE, color=MUTED, size=14),
                                ft.Text(
                                    'Пароль сохранится в локальном JSON с правами 600.',
                                    color=MUTED,
                                    size=10,
                                ),
                            ],
                        ),
                    ],
                ),
            ),
        )
        self.root.controls.append(
            ft.Row(
                expand=True,
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[hero, form],
            )
        )
        self.page.update()

    def _inspect_components(self):
        """Read KeeneticOS component states using the active runtime session."""
        client = create_router_client()
        try:
            return inspect_components(client)
        finally:
            client.disconnect()

    def _bootstrap_inventory_if_needed(self):
        """Recover existing router routes when the local registry is empty.

        Returns:
            A short user-facing import summary, or an empty string when the
            registry already contains managed domains.

        Side effects:
            Reads live WireGuard routes and public attribution lists, stores
            their ownership in SQLite, and registers known single-tunnel DNS
            domains.  The router configuration is never changed.
        """
        if list_managed_domains():
            return ''
        inventory = import_current_inventory()
        linked = reconcile_inventory_domains()
        return (
            f'Найдено маршрутов: {inventory["routes"]} · '
            f'восстановлено доменов: {linked.registered}'
        )

    def render_dashboard(self):
        """Assemble the authenticated router dashboard."""
        self.status_text.value = self.initial_status
        self.root.controls.clear()
        self.root.controls.extend(
            [
                self._header(),
                self._component_notice(),
                ft.Row(
                    expand=True,
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[self._left_panel(), self._detail_panel()],
                ),
            ]
        )
        self.page.update()

    def _component_notice(self):
        """Show a repair action only when SSH or WireGuard is missing."""
        missing = [
            name
            for name in ('ssh', 'wireguard')
            if self.component_states.get(name) is not None
            and not self.component_states[name].installed
        ]
        if not missing:
            return ft.Container(visible=False)
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=24, vertical=10),
            bgcolor='#2B2414',
            border=ft.Border(bottom=ft.BorderSide(1, '#5B4A1B')),
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.BUILD_CIRCLE_OUTLINED, color='#FFD36A'),
                    ft.Text(
                        f'Не установлены компоненты: {", ".join(missing)}. Установка может перезагрузить роутер.',
                        color=TEXT,
                        expand=True,
                    ),
                    ft.Button('Установить', color=BG, bgcolor='#FFD36A', on_click=self.confirm_components),
                ]
            ),
        )

    def disconnect_router(self, _event=None):
        """Forget session credentials and return to the connection screen."""
        clear_runtime_connection()
        self.password = self.profile.password
        self.report = None
        self.tunnels = {}
        self.tunnel_labels = {}
        self.tunnel_statuses = {}
        self.component_states = {}
        self.render_login()

    def confirm_components(self, _event=None):
        """Require explicit consent before a component firmware commit."""
        missing = [
            name
            for name in ('ssh', 'wireguard')
            if self.component_states.get(name) is not None
            and not self.component_states[name].installed
        ]
        if not missing:
            return

        async def apply(_event=None):
            self.page.pop_dialog()
            await self.set_busy(True, 'KeeneticOS устанавливает компоненты…')

            def install():
                client = create_router_client()
                try:
                    return install_components(client, missing)
                finally:
                    try:
                        client.disconnect()
                    except Exception:
                        pass

            try:
                result = await asyncio.to_thread(install)
            except Exception as exception:
                await self.set_busy(False, f'Ошибка установки: {exception}')
                return
            await self.set_busy(False)
            if result.errors:
                self.status_text.value = ' · '.join(result.errors)
            elif result.reboot_expected:
                self.status_text.value = 'Компоненты применяются; после перезагрузки подключись заново'
            else:
                self.status_text.value = 'Нужные компоненты уже установлены'
            self.page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Установить компоненты KeeneticOS?'),
            content=ft.Text(
                f'Будут выбраны: {", ".join(missing)}. Команда components commit может '
                'обновить KeeneticOS, оборвать соединение и перезагрузить роутер.'
            ),
            actions=[
                ft.Button('Отмена', on_click=lambda _event: self.page.pop_dialog()),
                ft.Button('Установить и разрешить перезагрузку', bgcolor='#FFD36A', color=BG, on_click=apply),
            ],
        )
        self.page.show_dialog(dialog)

    def reopen_vpn_manager(self, _event=None):
        """Close the current VPN subdialog and return to the profile list."""
        self.page.pop_dialog()
        self.open_vpn_manager()

    def open_vpn_manager(self, _event=None):
        """Show existing named VPN profiles and their safe management actions."""
        cards = []
        for short, interface in sorted(self.tunnels.items()):
            name = self.tunnel_display_name(short)
            status = self.tunnel_statuses.get(short, 'unknown')
            active_domains = sum(
                1 for row in self.rows if row['enabled'] and row['tunnel'] == short
            )
            status_up = status == 'up'
            cards.append(
                ft.Container(
                    padding=14,
                    border_radius=14,
                    bgcolor=PANEL,
                    border=ft.Border.all(1, LINE),
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                width=42,
                                height=42,
                                border_radius=12,
                                alignment=ft.Alignment.CENTER,
                                bgcolor=ft.Colors.with_opacity(
                                    0.12,
                                    ACID if status_up else MUTED,
                                ),
                                content=ft.Icon(
                                    ft.Icons.SHIELD_OUTLINED,
                                    color=ACID if status_up else MUTED,
                                ),
                            ),
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(name, color=TEXT, size=16, weight=ft.FontWeight.BOLD),
                                    ft.Text(
                                        f'{interface} · {short} · сайтов: {active_domains}',
                                        color=MUTED,
                                        size=10,
                                    ),
                                ],
                            ),
                            ft.Container(
                                padding=ft.Padding.symmetric(horizontal=9, vertical=4),
                                border_radius=18,
                                bgcolor=ft.Colors.with_opacity(
                                    0.12,
                                    ACID if status_up else MUTED,
                                ),
                                content=ft.Text(
                                    'ВКЛ' if status_up else 'ВЫКЛ',
                                    color=ACID if status_up else MUTED,
                                    size=9,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.EDIT_OUTLINED,
                                icon_color=MUTED,
                                tooltip='Переименовать',
                                on_click=lambda _event, selected=short: self.open_rename_tunnel(
                                    selected
                                ),
                            ),
                            ft.IconButton(
                                icon=(
                                    ft.Icons.POWER_SETTINGS_NEW
                                    if status_up
                                    else ft.Icons.PLAY_ARROW
                                ),
                                icon_color=DANGER if status_up else ACID,
                                tooltip='Отключить' if status_up else 'Включить',
                                on_click=lambda _event, selected=short: self.confirm_tunnel_toggle(
                                    selected
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color=DANGER,
                                tooltip='Удалить VPN',
                                on_click=lambda _event, selected=short: self.confirm_tunnel_delete(
                                    selected
                                ),
                            ),
                        ]
                    ),
                )
            )
        if not cards:
            cards.append(
                ft.Container(
                    padding=28,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text('На роутере пока нет WireGuard-профилей', color=MUTED),
                )
            )

        def add_new(_event=None):
            self.page.pop_dialog()
            self.open_tunnel_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Настройка VPN'),
            content=ft.Column(
                width=700,
                height=430,
                spacing=12,
                controls=[
                    ft.Text(
                        'Показываются названия, заданные в Keenetic. Технические имена оставлены мелко.',
                        color=MUTED,
                        size=11,
                    ),
                    ft.ListView(expand=True, spacing=8, controls=cards),
                ],
            ),
            actions=[
                ft.Button('Закрыть', on_click=lambda _event: self.page.pop_dialog()),
                ft.Button(
                    'Добавить VPN',
                    icon=ft.Icons.ADD,
                    bgcolor=ACID,
                    color=BG,
                    on_click=add_new,
                ),
            ],
        )
        self.page.show_dialog(dialog)

    def open_rename_tunnel(self, short):
        """Request and persist a new user-facing name for one VPN profile."""
        self.page.pop_dialog()
        interface = self.tunnels[short]
        field = ft.TextField(
            label='Название VPN',
            value=self.tunnel_display_name(short),
            hint_text='Например: Домашний VPN',
            autofocus=True,
        )

        async def apply(_event=None):
            value = (field.value or '').strip()
            if not value:
                field.error = 'Введите название VPN'
                self.page.update()
                return
            self.page.pop_dialog()
            await self.set_busy(True, f'Переименовываю {interface}…')

            def rename():
                client = create_router_client()
                try:
                    return rename_wireguard_tunnel(client, interface, value)
                finally:
                    client.disconnect()

            try:
                saved = await asyncio.to_thread(rename)
            except Exception as exception:
                await self.set_busy(False, f'Не удалось переименовать {interface}')
                self._show_error(str(exception))
                return
            self.tunnel_labels[short] = saved
            await self.set_busy(False, f'{interface} теперь называется «{saved}»')
            self.render_dashboard()
            self.reload_data()
            self.open_vpn_manager()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f'Переименовать {self.tunnel_display_name(short)}'),
            content=ft.Container(width=420, content=field),
            actions=[
                ft.Button('Отмена', on_click=self.reopen_vpn_manager),
                ft.Button('Сохранить', bgcolor=ACID, color=BG, on_click=apply),
            ],
        )
        self.page.show_dialog(dialog)

    def confirm_tunnel_toggle(self, short):
        """Confirm a live up/down change before mutating the router."""
        self.page.pop_dialog()
        status_up = self.tunnel_statuses.get(short) == 'up'
        enable = not status_up
        active_domains = sum(
            1 for row in self.rows if row['enabled'] and row['tunnel'] == short
        )
        action = 'Включить' if enable else 'Отключить'
        warning = (
            f'Через этот VPN идут сайты: {active_domains}. Пока VPN выключен, они могут не открываться.'
            if status_up and active_domains
            else 'Настройка будет сохранена на роутере.'
        )

        async def apply(_event=None):
            self.page.pop_dialog()
            await self.set_busy(True, f'{action} {self.tunnel_display_name(short)}…')

            def toggle():
                client = create_router_client()
                try:
                    return set_wireguard_tunnel_enabled(
                        client,
                        self.tunnels[short],
                        enable,
                    )
                finally:
                    client.disconnect()

            try:
                await asyncio.to_thread(toggle)
            except Exception as exception:
                await self.set_busy(False, f'Не удалось изменить состояние {self.tunnels[short]}')
                self._show_error(str(exception))
                return
            self.tunnel_statuses[short] = 'up' if enable else 'down'
            await self.set_busy(False, f'{self.tunnel_display_name(short)}: {action.lower()}')
            self.render_dashboard()
            self.reload_data()
            self.open_vpn_manager()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f'{action} {self.tunnel_display_name(short)}?'),
            content=ft.Text(warning),
            actions=[
                ft.Button('Отмена', on_click=self.reopen_vpn_manager),
                ft.Button(action, color=BG if enable else DANGER, bgcolor=ACID if enable else None, on_click=apply),
            ],
        )
        self.page.show_dialog(dialog)

    def confirm_tunnel_delete(self, short):
        """Block in-use VPN deletion and confirm an unused interface removal."""
        self.page.pop_dialog()
        active_domains = [
            row['domain']
            for row in self.rows
            if row['enabled'] and row['tunnel'] == short
        ]
        if active_domains:
            preview = ', '.join(active_domains[:4])
            suffix = '…' if len(active_domains) > 4 else ''
            self._show_error(
                f'Сначала отключите сайты, использующие этот VPN: {preview}{suffix}'
            )
            return
        interface = self.tunnels[short]

        async def apply(_event=None):
            self.page.pop_dialog()
            await self.set_busy(True, f'Удаляю {self.tunnel_display_name(short)}…')

            def delete():
                client = create_router_client()
                try:
                    delete_wireguard_tunnel(client, interface)
                finally:
                    client.disconnect()

            try:
                await asyncio.to_thread(delete)
            except Exception as exception:
                await self.set_busy(False, f'Не удалось удалить {interface}')
                self._show_error(str(exception))
                return
            name = self.tunnel_display_name(short)
            self.tunnels.pop(short, None)
            self.tunnel_labels.pop(short, None)
            self.tunnel_statuses.pop(short, None)
            await self.set_busy(False, f'VPN «{name}» удалён')
            self.render_dashboard()
            self.reload_data()
            self.open_vpn_manager()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f'Удалить {self.tunnel_display_name(short)}?'),
            content=ft.Text(
                f'{interface} будет удалён из конфигурации Keenetic. Это действие нельзя отменить.'
            ),
            actions=[
                ft.Button('Отмена', on_click=self.reopen_vpn_manager),
                ft.Button('Удалить VPN', color=DANGER, on_click=apply),
            ],
        )
        self.page.show_dialog(dialog)

    def open_tunnel_dialog(self, _event=None):
        """Offer a WireGuard configuration file or QR image source."""

        async def choose(qr):
            self.page.pop_dialog()
            files = await self.file_picker.pick_files(
                dialog_title='Выберите WireGuard QR' if qr else 'Выберите WireGuard конфигурацию',
                file_type=ft.FilePickerFileType.IMAGE if qr else ft.FilePickerFileType.CUSTOM,
                allowed_extensions=None if qr else ['conf'],
                allow_multiple=False,
            )
            if not files:
                return
            selected = files[0]
            if not selected.path:
                self._show_error('Приложение не получило локальный путь к выбранному файлу')
                return
            try:
                profile = await asyncio.to_thread(
                    load_wireguard_qr if qr else load_wireguard_file,
                    selected.path,
                )
            except Exception as exception:
                self._show_error(str(exception))
                return
            self._show_tunnel_preview(profile, selected.name)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Добавить WireGuard'),
            content=ft.Text(
                'Загрузите стандартный WireGuard .conf или изображение QR. Приватный ключ '
                'будет передан только по SSH и не сохранится в журнале приложения.'
            ),
            actions=[
                ft.Button('Отмена', on_click=lambda _event: self.page.pop_dialog()),
                ft.Button(
                    'Файл .conf',
                    icon=ft.Icons.DESCRIPTION_OUTLINED,
                    on_click=lambda _event: self.page.run_task(choose, False),
                ),
                ft.Button(
                    'QR-код',
                    icon=ft.Icons.IMAGE_OUTLINED,
                    bgcolor=ACID,
                    color=BG,
                    on_click=lambda _event: self.page.run_task(choose, True),
                ),
            ],
        )
        self.page.show_dialog(dialog)

    def _show_tunnel_preview(self, profile, source_name):
        """Show a non-secret import summary and apply it after confirmation."""
        summary = profile.summary
        suggested = source_name.rsplit('.', 1)[0][:64] or 'WireGuard VPN'
        name = ft.TextField(
            label='Название VPN в Keenetic',
            value=suggested,
            hint_text='Например: Домашний VPN',
            helper_text='Это имя будет показано при выборе маршрута для сайта.',
        )
        via = ft.TextField(label='Выход к VPN-серверу', value='ISP', hint_text='ISP')
        interface = ft.TextField(label='Интерфейс (необязательно)', hint_text='Автоматически: Wireguard2')

        async def apply(_event=None):
            self.page.pop_dialog()
            await self.set_busy(True, 'Создаю WireGuard-туннель…')

            def import_profile():
                client = create_router_client()
                try:
                    return import_wireguard_profile(
                        client,
                        profile,
                        description=name.value or 'WireGuard VPN',
                        via=via.value or 'ISP',
                        interface=(interface.value or '').strip() or None,
                    )
                finally:
                    client.disconnect()

            try:
                result = await asyncio.to_thread(import_profile)
            except Exception as exception:
                await self.set_busy(False, f'Импорт не выполнен: {exception}')
                return
            short = result.interface.lower().replace('wireguard', 'wg')
            self.tunnels[short] = result.interface
            self.tunnel_labels[short] = (name.value or 'WireGuard VPN').strip()
            self.tunnel_statuses[short] = 'up'
            await self.set_busy(False, f'{result.interface} создан и сохранён')
            self.render_dashboard()
            self.reload_data()

        endpoints = ', '.join(summary['endpoints']) or 'не указан'
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Проверенный WireGuard-профиль'),
            content=ft.Column(
                tight=True,
                width=520,
                controls=[
                    ft.Text(
                        f'Адрес: {", ".join(summary["addresses"])}\n'
                        f'Пиров: {summary["peer_count"]} · Endpoint: {endpoints}\n'
                        f'AllowedIPs: {summary["allowed_ip_count"]}',
                        color=MUTED,
                    ),
                    name,
                    via,
                    interface,
                    ft.Text('Применение создаст новый интерфейс и сохранит конфигурацию KeeneticOS.', size=11),
                ],
            ),
            actions=[
                ft.Button('Отмена', on_click=lambda _event: self.page.pop_dialog()),
                ft.Button('Создать туннель', bgcolor=ACID, color=BG, on_click=apply),
            ],
        )
        self.page.show_dialog(dialog)

    def _show_error(self, message):
        """Display one blocking error without changing the dashboard state."""
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Не получилось'),
            content=ft.Text(message),
            actions=[ft.Button('Закрыть', on_click=lambda _event: self.page.pop_dialog())],
        )
        self.page.show_dialog(dialog)

    async def check_for_updates(self, _event=None, manual=False):
        """Check GitHub in the background and show a stable update notice.

        Automatic failures stay silent so an unavailable network never blocks
        router work. Manual checks show a useful error dialog.
        """
        if self.update_button is not None:
            self.update_button.disabled = True
            self.update_button.icon = ft.Icons.HOURGLASS_TOP
            self.page.update()
        try:
            info = await asyncio.to_thread(fetch_latest_release)
        except Exception as exception:
            if self.update_button is not None:
                self.update_button.disabled = False
                self.update_button.icon = ft.Icons.SYSTEM_UPDATE_ALT
                self.page.update()
            if manual:
                self._show_error(f'Не удалось проверить обновления: {exception}')
            return
        self.update_info = info
        if self.update_button is not None:
            self.update_button.disabled = False
            self.update_button.icon = (
                ft.Icons.DOWNLOAD_FOR_OFFLINE if info.available else ft.Icons.SYSTEM_UPDATE_ALT
            )
            self.update_button.icon_color = ACID if info.available else MUTED
            self.update_button.tooltip = (
                f'Доступно обновление {info.latest_version}'
                if info.available
                else f'Установлена свежая версия {__version__}'
            )
        if info.available:
            notice = ft.SnackBar(
                content=ft.Text(
                    f'Вышла новая версия PackeTech {info.latest_version}',
                    color=TEXT,
                    weight=ft.FontWeight.BOLD,
                ),
                action='Скачать',
                on_action=self.open_update_manager,
                bgcolor=PANEL_ACTIVE,
                show_close_icon=True,
                close_icon_color=MUTED,
                duration=10000,
            )
            self.page.show_dialog(notice)
        elif manual:
            self.open_update_manager()
        self.page.update()

    def open_update_manager(self, _event=None):
        """Show version state and download a verified native package."""
        info = self.update_info
        if info is None:
            self.page.run_task(self.check_for_updates, None, True)
            return
        progress = ft.ProgressBar(value=0, color=ACID, bgcolor=LINE, height=5)
        progress_slot = ft.Container(height=5, content=progress, visible=False)
        detail = ft.Text(
            installation_hint() if info.available else 'У вас уже установлена последняя версия.',
            color=MUTED,
            size=12,
        )

        async def download(_event=None):
            if info.asset is None:
                self._show_error('Для этой системы пока нет готовой сборки PackeTech.')
                return
            download_button.disabled = True
            download_button.content = ft.Row(
                tight=True,
                spacing=9,
                controls=[
                    ft.ProgressRing(width=16, height=16, stroke_width=2, color=BG),
                    ft.Text('Скачиваю…', weight=ft.FontWeight.BOLD),
                ],
            )
            progress_slot.visible = True
            self.page.update()
            loop = asyncio.get_running_loop()

            def report(received, total):
                def apply_progress():
                    progress.value = received / total if total else None
                    self.page.update()

                loop.call_soon_threadsafe(apply_progress)

            try:
                path = await asyncio.to_thread(download_update, info, callback=report)
            except Exception as exception:
                download_button.disabled = False
                download_button.content = 'Скачать обновление'
                download_button.icon = ft.Icons.DOWNLOAD
                progress_slot.visible = False
                self.page.update()
                self._show_error(str(exception))
                return
            progress.value = 1
            detail.value = f'Файл проверен и сохранён:\n{path}\n\n{installation_hint()}'
            download_button.disabled = False
            download_button.content = 'Открыть установку'
            download_button.icon = ft.Icons.OPEN_IN_NEW
            download_button.on_click = lambda _e: open_downloaded_update(Path(path))
            self.page.update()
            open_downloaded_update(path)

        if info.available:
            if info.asset is None:
                button_label = 'Сборки для этой системы нет'
                button_disabled = True
            else:
                button_label = 'Скачать обновление'
                button_disabled = False
            download_button = ft.Button(
                button_label,
                icon=ft.Icons.DOWNLOAD,
                bgcolor=ACID,
                color=BG,
                disabled=button_disabled,
                on_click=download,
            )
        else:
            download_button = ft.Button(
                'Готово',
                bgcolor=ACID,
                color=BG,
                on_click=lambda _e: self.page.pop_dialog(),
            )
        size_text = ''
        if info.asset and info.asset.size:
            size_text = f' · {info.asset.size / 1024 / 1024:.0f} МБ'
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Обновление PackeTech'),
            content=ft.Column(
                tight=True,
                width=500,
                spacing=14,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(f'Сейчас: {info.current_version}', color=MUTED),
                            ft.Icon(ft.Icons.ARROW_FORWARD, color=MUTED, size=16),
                            ft.Text(f'На GitHub: {info.latest_version}', color=ACID),
                        ]
                    ),
                    ft.Text(
                        f'{info.asset.name}{size_text}' if info.asset else 'Нет совместимого файла',
                        color=TEXT,
                        weight=ft.FontWeight.BOLD,
                    ),
                    detail,
                    progress_slot,
                ],
            ),
            actions=[
                ft.Button('Закрыть', on_click=lambda _e: self.page.pop_dialog()),
                download_button,
            ],
        )
        self.page.show_dialog(dialog)

    def open_chrome_manager(self, _event=None):
        """Show the guided Chrome extension installation flow.

        PackeTech performs every local setup step itself. Chrome intentionally
        keeps the final unpacked-extension confirmation under direct user
        control, so the dialog explains that single remaining action and opens
        both required windows.
        """
        browser = detect_chrome()
        prepared = self.chrome_installation or inspect_chrome_extension(browser=browser)
        if prepared is not None:
            self.chrome_installation = prepared

        def step_card(number, title, description, *, complete=False):
            """Return one compact, consistently aligned installer step."""
            return ft.Container(
                padding=14,
                border_radius=14,
                bgcolor=PANEL if not complete else ft.Colors.with_opacity(0.08, ACID),
                border=ft.Border.all(1, ACID if complete else LINE),
                content=ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Container(
                            width=30,
                            height=30,
                            border_radius=9,
                            alignment=ft.Alignment.CENTER,
                            bgcolor=ACID if complete else PANEL_ACTIVE,
                            content=ft.Icon(
                                ft.Icons.CHECK if complete else None,
                                color=BG if complete else TEXT,
                                size=17,
                            ) if complete else ft.Text(
                                str(number),
                                color=TEXT,
                                weight=ft.FontWeight.BOLD,
                            ),
                        ),
                        ft.Column(
                            expand=True,
                            spacing=3,
                            controls=[
                                ft.Text(title, color=TEXT, weight=ft.FontWeight.BOLD),
                                ft.Text(description, color=MUTED, size=11),
                            ],
                        ),
                    ],
                ),
            )

        async def install(_event=None):
            install_button.disabled = True
            install_button.content = ft.Row(
                tight=True,
                spacing=9,
                controls=[
                    ft.ProgressRing(width=16, height=16, stroke_width=2, color=BG),
                    ft.Text('Готовлю расширение…', weight=ft.FontWeight.BOLD),
                ],
            )
            self.page.update()
            try:
                result = await asyncio.to_thread(prepare_chrome_extension, browser=browser)
                self.chrome_installation = result
                await asyncio.to_thread(open_chrome_extensions, result.browser)
                await asyncio.to_thread(reveal_extension_directory, result.extension_directory)
            except Exception as exception:
                install_button.disabled = False
                install_button.content = 'Установить расширение'
                install_button.icon = ft.Icons.EXTENSION
                self.page.update()
                self._show_error(str(exception))
                return
            self.page.pop_dialog()
            self.open_chrome_manager()

        def open_extensions(_event=None):
            if browser:
                open_chrome_extensions(browser)

        def reveal_folder(_event=None):
            if prepared:
                reveal_extension_directory(prepared.extension_directory)

        if browser is None:
            browser_status = 'Google Chrome не найден'
            browser_color = DANGER
        else:
            browser_status = f'{browser.name} найден'
            browser_color = ACID

        if prepared:
            steps = [
                step_card(1, 'Файлы и помощник готовы', 'PackeTech уже связал расширение с общей базой.', complete=True),
                step_card(2, 'Откройте chrome://extensions', 'PackeTech уже открыл эту страницу в Chrome.', complete=True),
                step_card(
                    3,
                    'Подключите папку один раз',
                    'Включите «Режим разработчика» → нажмите «Загрузить распакованное расширение» → выберите открытую папку.',
                ),
            ]
            actions = [
                ft.Button('Открыть Chrome', icon=ft.Icons.OPEN_IN_NEW, on_click=open_extensions),
                ft.Button('Показать папку', icon=ft.Icons.FOLDER_OPEN, on_click=reveal_folder),
                ft.Button('Закрыть', bgcolor=ACID, color=BG, on_click=lambda _event: self.page.pop_dialog()),
            ]
        else:
            steps = [
                step_card(1, 'PackeTech подготовит расширение', 'Скопирует его в постоянную пользовательскую папку.'),
                step_card(2, 'Подключит локальный помощник', 'Расширение возьмет роутер и домены из тех же настроек PackeTech.'),
                step_card(3, 'Покажет последнее действие', 'Chrome попросит один раз выбрать готовую папку.'),
            ]
            install_button = ft.Button(
                'Установить расширение',
                icon=ft.Icons.EXTENSION,
                bgcolor=ACID,
                color=BG,
                disabled=browser is None,
                on_click=install,
            )
            actions = [
                ft.Button('Закрыть', on_click=lambda _event: self.page.pop_dialog()),
                install_button,
            ]

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                spacing=10,
                controls=[
                    ft.Icon(ft.Icons.EXTENSION, color=ACID),
                    ft.Text('Расширение Chrome'),
                ],
            ),
            content=ft.Column(
                width=620,
                tight=True,
                spacing=10,
                controls=[
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=12, vertical=9),
                        border_radius=12,
                        bgcolor=ft.Colors.with_opacity(0.08, browser_color),
                        content=ft.Row(
                            spacing=8,
                            controls=[
                                ft.Icon(ft.Icons.CIRCLE, color=browser_color, size=10),
                                ft.Text(browser_status, color=browser_color, size=11, weight=ft.FontWeight.BOLD),
                            ],
                        ),
                    ),
                    ft.Text(
                        'После установки значок PackeTech добавляет открытый сайт в общую базу и сразу обновляет маршруты.',
                        color=MUTED,
                        size=11,
                    ),
                    *steps,
                    ft.Text(
                        'Chrome специально не разрешает программам включать распакованные расширения без подтверждения пользователя.',
                        color=MUTED,
                        size=10,
                    ),
                ],
            ),
            actions=actions,
        )
        self.page.show_dialog(dialog)

    def _header(self):
        transport = (self.report.transport if self.report else 'offline').upper()
        self.sync_button = ft.Button(
            icon=ft.Icons.SYNC,
            color=MUTED,
            elevation=0,
            height=44,
            width=48,
            tooltip='Проверить DNS и маршруты сейчас',
            on_click=self.sync_all,
        )
        self.update_button = ft.IconButton(
            icon=ft.Icons.SYSTEM_UPDATE_ALT,
            icon_color=MUTED,
            tooltip=f'Проверить обновления · сейчас {__version__}',
            on_click=lambda event: self.page.run_task(self.check_for_updates, event, True),
        )
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=24, vertical=18),
            border=ft.Border(bottom=ft.BorderSide(1, LINE)),
            content=ft.Row(
                controls=[
                    ft.Image(
                        src=BRAND_ICON,
                        width=46,
                        height=46,
                        fit=ft.BoxFit.CONTAIN,
                        filter_quality=ft.FilterQuality.NONE,
                    ),
                    ft.Column(
                        spacing=1,
                        controls=[
                            ft.Text(
                                f'PACKETECH · {self.profile.host} · {transport}',
                                color=ACID,
                                size=10,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text('Маршруты сайтов', color=TEXT, size=21, weight=ft.FontWeight.BOLD),
                            self.status_text,
                        ],
                    ),
                    ft.Container(expand=True),
                    ft.Button(
                        'Настройка VPN',
                        icon=ft.Icons.TUNE,
                        color=TEXT,
                        bgcolor=PANEL_ACTIVE,
                        elevation=0,
                        height=44,
                        on_click=self.open_vpn_manager,
                    ),
                    ft.Button(
                        'Chrome',
                        icon=ft.Icons.EXTENSION,
                        color=TEXT,
                        bgcolor=PANEL_ACTIVE,
                        elevation=0,
                        height=44,
                        on_click=self.open_chrome_manager,
                    ),
                    self.sync_button,
                    self.update_button,
                    ft.IconButton(
                        icon=ft.Icons.LOGOUT,
                        icon_color=MUTED,
                        tooltip='Отключиться от роутера',
                        on_click=self.disconnect_router,
                    ),
                ]
            ),
        )

    def _left_panel(self):
        return ft.Container(
            width=480,
            padding=20,
            border=ft.Border(right=ft.BorderSide(1, LINE)),
            content=ft.Column(
                expand=True,
                controls=[
                    ft.Row(
                        controls=[
                            self.quick_domain,
                            ft.Button(
                                icon=ft.Icons.ADD,
                                color=BG,
                                bgcolor=ACID,
                                elevation=0,
                                height=48,
                                width=52,
                                tooltip='Добавить сайт',
                                on_click=self.quick_add_site,
                            ),
                        ]
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text('САЙТЫ', color=MUTED, size=10, weight=ft.FontWeight.BOLD),
                            self.domain_count_text,
                        ],
                    ),
                    self.domain_list,
                ],
            ),
        )

    def _detail_panel(self):
        return ft.Container(expand=True, padding=24, content=self.detail)

    def source_badges(self, row):
        """Build compact provenance chips for one database row."""
        badges = []
        for key in split_sources(row['sources']):
            color = ACID if key == 'chrome' else '#83B9FF' if key == 'desktop' else '#D4B6FF'
            badges.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                    border_radius=20,
                    bgcolor=ft.Colors.with_opacity(0.12, color),
                    content=ft.Text(source_label(key), color=color, size=9, weight=ft.FontWeight.BOLD),
                )
            )
        return badges

    @staticmethod
    def domain_avatar(domain, radius=20):
        """Return a remote favicon with a readable local letter fallback.

        Args:
            domain: Validated managed hostname.
            radius: Avatar radius in logical pixels.

        Returns:
            Flet avatar.  Failure of the external image never hides the domain
            because the first letter remains as background content.
        """
        return ft.CircleAvatar(
            radius=radius,
            foreground_image_src=favicon_url(domain, 64),
            bgcolor=PANEL_ACTIVE,
            color=ACID,
            content=ft.Text(domain[0].upper(), weight=ft.FontWeight.BOLD),
        )

    def tunnel_display_name(self, short_name):
        """Return a router-assigned VPN name before its technical identifier."""
        return self.tunnel_labels.get(short_name) or self.tunnels.get(short_name) or short_name

    def render_domains(self, _event=None):
        """Rebuild the domain list without contacting the router."""
        self.domain_list.controls.clear()
        visible = self.rows
        self.domain_count_text.value = f'{len(self.rows)} добавлено'
        if not visible:
            self.domain_list.controls.append(
                ft.Container(
                    padding=24,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text(
                        'Сайтов пока нет. Нажми «Добавить сайт», чтобы создать первый маршрут.',
                        color=MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                )
            )
        for row in visible:
            selected = row['id'] == self.selected_id
            badges = self.source_badges(row)
            enabled = bool(row['enabled'])
            self.domain_list.controls.append(
                ft.Container(
                    data=row['id'],
                    padding=12,
                    border_radius=14,
                    bgcolor=PANEL_ACTIVE if selected else PANEL,
                    border=ft.Border.all(1, ACID if selected else LINE),
                    on_click=self.select_domain,
                    content=ft.Row(
                        controls=[
                            self.domain_avatar(row['domain']),
                            ft.Column(
                                expand=True,
                                spacing=5,
                                controls=[
                                    ft.Text(
                                        row['domain'],
                                        color=TEXT if enabled else MUTED,
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Row(spacing=5, wrap=True, controls=badges),
                                ],
                            ),
                            ft.Container(
                                width=108,
                                padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                                border_radius=18,
                                alignment=ft.Alignment.CENTER,
                                bgcolor=ft.Colors.with_opacity(0.12, ACID if enabled else MUTED),
                                content=ft.Text(
                                    self.tunnel_display_name(row['tunnel']) if enabled else 'выкл.',
                                    color=ACID if enabled else MUTED,
                                    size=10,
                                    weight=ft.FontWeight.BOLD,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                tooltip=(
                                    f'{self.tunnel_display_name(row["tunnel"])} · '
                                    f'{row["tunnel"]} · {self.tunnels.get(row["tunnel"], "WireGuard")}'
                                ),
                            ),
                            ft.Icon(ft.Icons.CHEVRON_RIGHT, color=MUTED, size=17),
                        ]
                    ),
                )
            )
        self.page.update()

    def select_domain(self, event):
        """Select a row from the list and render its everyday controls."""
        self.selected_id = event.control.data
        self.render_domains()
        self.render_detail()

    def selected_row(self):
        """Return the current domain row, or ``None`` when nothing is selected."""
        return next((row for row in self.rows if row['id'] == self.selected_id), None)

    def render_detail(self):
        """Render only the selected domain's primary everyday controls."""
        self.detail.controls.clear()
        row = self.selected_row()
        if row is None:
            self.detail.controls.extend(
                [
                    ft.Container(expand=True),
                    ft.Icon(ft.Icons.TRAVEL_EXPLORE, color=LINE, size=64),
                    ft.Text('Выбери домен слева', color=MUTED, size=15),
                    ft.Container(expand=True),
                ]
            )
            self.page.update()
            return

        sources = split_sources(row['sources'])
        secondary_actions = []
        if 'chrome' in sources:
            secondary_actions.append(
                ft.Button(
                    'Убрать метку Chrome',
                    icon=ft.Icons.TIMER_OFF,
                    color=TEXT,
                    bgcolor=PANEL_ACTIVE,
                    elevation=0,
                    on_click=self.release_chrome,
                )
            )
        enabled = bool(row['enabled'])
        state_button = ft.Button(
            'Отключить' if enabled else 'Включить',
            icon=ft.Icons.POWER_SETTINGS_NEW,
            color=DANGER if enabled else BG,
            bgcolor='#2B1716' if enabled else ACID,
            elevation=0,
            on_click=self.confirm_disable if enabled else self.enable_domain,
        )
        route_count = row['inventory_route_count'] + row['address_count']

        self.detail.controls.extend(
            [
                ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        self.domain_avatar(row['domain'], radius=28),
                        ft.Column(
                            expand=True,
                            spacing=6,
                            controls=[
                                ft.Text(row['domain'], color=TEXT, size=27, weight=ft.FontWeight.BOLD),
                                ft.Row(spacing=6, wrap=True, controls=self.source_badges(row)),
                            ],
                        ),
                        state_button,
                    ],
                ),
                ft.Container(height=8),
                ft.Container(
                    padding=22,
                    border_radius=18,
                    bgcolor=PANEL,
                    border=ft.Border.all(1, LINE),
                    content=ft.Row(
                        spacing=16,
                        controls=[
                            ft.Container(
                                width=48,
                                height=48,
                                border_radius=14,
                                bgcolor=ft.Colors.with_opacity(0.12, ACID),
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(ft.Icons.ROUTE, color=ACID, size=24),
                            ),
                            ft.Column(
                                expand=True,
                                spacing=3,
                                controls=[
                                    ft.Text('МАРШРУТ ЧЕРЕЗ', color=MUTED, size=9, weight=ft.FontWeight.BOLD),
                                    ft.Text(
                                        self.tunnel_display_name(row['tunnel']) if enabled else 'Отключён',
                                        color=TEXT,
                                        size=22,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(
                                        (
                                            f'{self.tunnels.get(row["tunnel"], "WireGuard")} · '
                                            f'{row["tunnel"]}'
                                            if enabled
                                            else 'Трафик сайта не перенаправляется'
                                        ),
                                        color=MUTED,
                                        size=11,
                                    ),
                                ],
                            ),
                            ft.Container(
                                padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                                border_radius=20,
                                bgcolor=ft.Colors.with_opacity(0.12, ACID if enabled else MUTED),
                                content=ft.Text(
                                    'ВКЛЮЧЁН' if enabled else 'ВЫКЛЮЧЕН',
                                    color=ACID if enabled else MUTED,
                                    size=9,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ),
                        ],
                    ),
                ),
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Button(
                            f'Технические данные · {route_count}',
                            icon=ft.Icons.TUNE,
                            color=TEXT,
                            bgcolor=PANEL_ACTIVE,
                            elevation=0,
                            on_click=self.open_technical_dialog,
                        ),
                        *secondary_actions,
                    ],
                ),
                ft.Container(expand=True),
                ft.Row(
                    spacing=7,
                    controls=[
                        ft.Icon(ft.Icons.SCHEDULE, color=MUTED, size=15),
                        ft.Text(
                            f'Последняя проверка: {self.short_date(row["last_resolved_at"])} · обновление каждые 6 часов',
                            color=MUTED,
                            size=11,
                        ),
                    ],
                ),
            ]
        )
        self.page.update()

    def open_technical_dialog(self, _event=None):
        """Show DNS addresses and published CIDRs outside the main workflow."""
        row = self.selected_row()
        if row is None:
            return
        addresses = domain_addresses(row['id'])
        inventory_routes = domain_inventory_routes(row['id'])
        entries = []
        for address in addresses:
            entries.append(
                self._technical_row(
                    address['address'],
                    'DNS',
                    address['last_seen_at'][0:16].replace('T', ' '),
                )
            )
        for route in inventory_routes:
            entries.append(
                self._technical_row(
                    route['network'],
                    'CIDR',
                    f'{route["source_kind"]}:{route["source_name"]} · {route["interface"]}',
                )
            )
        if not entries:
            entries.append(ft.Text('Адреса ещё не получены. Нажмите «Обновить».', color=MUTED))
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f'Технические данные · {row["domain"]}'),
            content=ft.Column(
                width=760,
                height=540,
                spacing=14,
                controls=[
                    ft.Row(
                        controls=[
                            self._technical_hint(
                                ft.Icons.LANGUAGE,
                                'DNS IP',
                                'Точный IPv4- или IPv6-адрес из последней DNS-проверки.',
                            ),
                            self._technical_hint(
                                ft.Icons.ACCOUNT_TREE_OUTLINED,
                                'CIDR',
                                'Диапазон IPv4- или IPv6-адресов из списка сервиса.',
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            ft.Text('АДРЕС', color=MUTED, size=9, expand=True),
                            ft.Text('ТИП', color=MUTED, size=9, width=60),
                            ft.Text('ИСТОЧНИК / ОБНОВЛЕНИЕ', color=MUTED, size=9, width=260),
                        ]
                    ),
                    ft.ListView(expand=True, spacing=6, controls=entries),
                    ft.Text(
                        'Эти значения обновляются автоматически. Редактировать их вручную не нужно.',
                        color=MUTED,
                        size=10,
                    ),
                ],
            ),
            actions=[ft.Button('Закрыть', on_click=lambda _event: self.page.pop_dialog())],
        )
        self.page.show_dialog(dialog)

    @staticmethod
    def _technical_hint(icon, title, description):
        """Return one compact explanation card for a networking term."""
        return ft.Container(
            expand=True,
            padding=14,
            border_radius=12,
            bgcolor=PANEL,
            border=ft.Border.all(1, LINE),
            content=ft.Row(
                spacing=10,
                controls=[
                    ft.Icon(icon, color=ACID, size=22),
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text(title, color=TEXT, weight=ft.FontWeight.BOLD),
                            ft.Text(description, color=MUTED, size=10),
                        ],
                    ),
                ],
            ),
        )

    @staticmethod
    def _technical_row(address, kind, detail):
        """Return one aligned address row for the technical dialog."""
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=10,
            bgcolor=PANEL,
            content=ft.Row(
                controls=[
                    ft.Text(address, color=TEXT, font_family='monospace', size=12, expand=True),
                    ft.Text(kind, color=ACID if kind == 'DNS' else '#83B9FF', size=10, width=60),
                    ft.Text(detail, color=MUTED, size=10, width=260),
                ],
            ),
        )

    @staticmethod
    def short_date(value):
        """Format a stored ISO timestamp for a compact dashboard metric."""
        return value[5:16].replace('T', ' ') if value else 'ещё не было'

    def reload_data(self):
        """Reload registry rows and preserve selection when possible."""
        reconcile_inventory_domains()
        self.rows = list(list_managed_domains())
        if self.selected_id is None and self.rows:
            self.selected_id = self.rows[0]['id']
        if self.selected_id and not any(row['id'] == self.selected_id for row in self.rows):
            self.selected_id = self.rows[0]['id'] if self.rows else None
        runs = recent_runs(1)
        if runs:
            self.status_text.value = f"Последнее обновление: {self.short_date(runs[0]['finished_at'] or runs[0]['started_at'])}"
        self.render_domains()
        self.render_detail()

    async def set_busy(self, value, text=None):
        """Lock manual sync in place and update the compact status text."""
        self.busy = value
        if self.sync_button is not None:
            # ``sync_all`` already ignores a second click while busy. Keeping
            # the control enabled prevents Flet from dimming its inline loader.
            self.sync_button.disabled = False
            if value:
                self.sync_button.icon = None
                self.sync_button.content = ft.ProgressRing(
                    width=16,
                    height=16,
                    stroke_width=2,
                    color=ACID,
                )
            else:
                self.sync_button.content = None
                self.sync_button.icon = ft.Icons.SYNC
        if text:
            self.status_text.value = text
        self.page.update()

    async def sync_all(self, _event=None):
        """Run the shared synchronizer outside the UI event loop."""
        if self.busy:
            return
        await self.set_busy(True, 'Обновляю DNS и маршруты…')
        try:
            summary = await asyncio.to_thread(sync_domains)
        except Exception as exception:
            await self.set_busy(False, f'Обновление не выполнено: {exception}')
            self._show_error(
                'Не удалось обновить маршруты. Проверь подключение к роутеру и VPN.\n\n'
                f'Причина: {exception}'
            )
            return
        await self.set_busy(False, f'Добавлено {summary.added} · без изменений {summary.unchanged} · ошибок {summary.errors}')
        self.reload_data()

    def quick_add_site(self, _event=None):
        """Validate the inline address and add it or request a VPN choice."""
        if not self.tunnels:
            self._show_error('Сначала добавьте и подключите WireGuard-туннель')
            return
        try:
            canonical = normalize_domain(self.quick_domain.value)
        except ValueError as error:
            self.quick_domain.error = str(error)
            self.page.update()
            return
        self.quick_domain.error = None
        self.quick_domain.value = canonical
        if len(self.tunnels) == 1:
            selected_tunnel = next(iter(self.tunnels))
            self.page.run_task(self.add_domain, canonical, selected_tunnel)
            return
        self.open_add_dialog(prefill=canonical)

    def open_add_dialog(self, _event=None, *, prefill=''):
        """Request a named VPN when more than one tunnel is available."""
        default_tunnel = sorted(self.tunnels)[0]
        domain_field = ft.TextField(
            label='Сайт',
            value=prefill,
            hint_text='example.com или https://example.com/page',
            autofocus=True,
            border_color=LINE,
            focused_border_color=ACID,
        )
        tunnel_field = ft.Dropdown(
            label='Туннель',
            value=default_tunnel,
            options=[
                ft.DropdownOption(
                    key=short,
                    text=f'{self.tunnel_display_name(short)} · {short} ({full})',
                )
                for short, full in sorted(self.tunnels.items())
            ],
        )

        async def submit(_event=None):
            try:
                canonical = normalize_domain(domain_field.value)
            except ValueError as error:
                domain_field.error = str(error)
                self.page.update()
                return
            self.page.pop_dialog()
            await self.add_domain(canonical, tunnel_field.value)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Добавить сайт'),
            content=ft.Column(tight=True, width=420, controls=[domain_field, tunnel_field]),
            actions=[
                ft.Button('Отмена', on_click=lambda _e: self.page.pop_dialog()),
                ft.Button('Добавить сайт', bgcolor=ACID, color=BG, on_click=submit),
            ],
        )
        self.page.show_dialog(dialog)

    async def add_domain(self, domain, tunnel):
        """Persist one canonical domain and immediately synchronize its routes."""
        canonical, _ = add_managed_domain(domain, tunnel, source='desktop')
        self.quick_domain.value = ''
        self.quick_domain.error = None
        self.reload_data()
        row = next(item for item in self.rows if item['domain'] == canonical)
        await self.set_busy(True, f'Добавляю {canonical}…')
        try:
            summary = await asyncio.to_thread(sync_domains, [row])
        except Exception as exception:
            await self.set_busy(False, f'{canonical} сохранён, но маршруты не обновлены')
            self._show_error(
                f'{canonical} добавлен в список, но Keenetic не обновлён.\n\n'
                f'Причина: {exception}'
            )
            return
        await self.set_busy(
            False,
            f'{canonical}: добавлено {summary.added}, ошибок {summary.errors}',
        )
        self.reload_data()

    async def enable_domain(self, _event=None):
        """Re-enable a disabled domain and immediately restore its routes."""
        row = self.selected_row()
        if row is None:
            return
        canonical, _ = add_managed_domain(
            row['domain'],
            row['tunnel'],
            source='desktop',
        )
        self.reload_data()
        updated = next(item for item in self.rows if item['domain'] == canonical)
        await self.set_busy(True, f'Включаю {canonical}…')
        try:
            summary = await asyncio.to_thread(sync_domains, [updated])
        except Exception as exception:
            await self.set_busy(False, f'{canonical} включён, но маршруты не обновлены')
            self._show_error(
                f'{canonical} снова включён, но Keenetic не обновлён.\n\n'
                f'Причина: {exception}'
            )
            return
        await self.set_busy(
            False,
            f'{canonical}: включён · добавлено {summary.added} · ошибок {summary.errors}',
        )
        self.reload_data()

    async def release_chrome(self, _event=None):
        """Release only Chrome ownership, preserving every other source."""
        row = self.selected_row()
        if row and remove_managed_domain(row['domain'], source='chrome'):
            updated = next(
                (item for item in list_managed_domains() if item['domain'] == row['domain']), None
            )
            cleanup = {'removed': 0, 'failed': 0}
            if updated is not None and not updated['enabled']:
                await self.set_busy(True, f'Удаляю временные маршруты {row["domain"]}…')
                try:
                    cleanup = await asyncio.to_thread(purge_domain_routes, row['domain'])
                except Exception as exception:
                    await self.set_busy(False, f'Метка Chrome снята, но маршруты не удалены')
                    self._show_error(str(exception))
                    self.reload_data()
                    return
                await self.set_busy(False)
            self.status_text.value = (
                f'Chrome снят: {row["domain"]} · удалено маршрутов {cleanup["removed"]}'
            )
            self.reload_data()

    def confirm_disable(self, _event=None):
        """Require confirmation before disabling every source of a domain."""
        row = self.selected_row()
        if row is None:
            return

        async def disable(_event=None):
            remove_managed_domain(row['domain'])
            self.page.pop_dialog()
            await self.set_busy(True, f'Проверяю маршруты {row["domain"]}…')
            try:
                cleanup = await asyncio.to_thread(purge_domain_routes, row['domain'])
            except Exception as exception:
                await self.set_busy(False, f'{row["domain"]} отключён, но маршруты не удалены')
                self._show_error(str(exception))
                self.reload_data()
                return
            await self.set_busy(False)
            self.status_text.value = (
                f'{row["domain"]}: отключён · удалено маршрутов {cleanup["removed"]}'
            )
            self.reload_data()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f'Отключить {row["domain"]}?'),
            content=ft.Text(
                'Будут отключены все источники. Удалятся только IP-маршруты без других владельцев; '
                'общие маршруты сохранятся.'
            ),
            actions=[
                ft.Button('Отмена', on_click=lambda _e: self.page.pop_dialog()),
                ft.Button('Отключить', color=DANGER, on_click=disable),
            ],
        )
        self.page.show_dialog(dialog)


def main(page: ft.Page):
    """Start the Flet desktop controller at the single-router login screen."""
    app = RouteDesktop(page)
    app.configure_page()


def run():
    """Launch the desktop runtime from an installed console entry point."""
    ft.run(main)


if __name__ == '__main__':
    run()
