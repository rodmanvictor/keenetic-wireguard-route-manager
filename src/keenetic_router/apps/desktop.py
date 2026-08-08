#!/usr/bin/env python3
"""Cross-platform Flet application for onboarding and route management.

The first screen authenticates to one router, enables SSH through Telnet when
possible, and keeps the password only in memory.  The dashboard remains a thin
layer over the shared registry, synchronizer, and WireGuard importer.
"""

import asyncio
from dataclasses import replace

import flet as ft

from keenetic_router.core.onboarding import (
    bootstrap_router,
    inspect_components,
    install_components,
)
from keenetic_router.core.profiles import RouterProfile, load_profile, save_profile
from keenetic_router.core.router import clear_runtime_connection, create_router_client
from keenetic_router.core.wireguard import (
    import_wireguard_profile,
    load_wireguard_file,
    load_wireguard_qr,
)
from keenetic_router.services.registry import (
    add_managed_domain,
    domain_addresses,
    domain_inventory_routes,
    list_managed_domains,
    recent_runs,
    remove_managed_domain,
    source_label,
    split_sources,
)
from keenetic_router.services.sync import sync_domains
from keenetic_router.services.cleanup import purge_domain_routes
from keenetic_router.services.catalog import reconcile_inventory_domains


BG = '#0B0E0C'
PANEL = '#151A16'
PANEL_ACTIVE = '#20281E'
LINE = '#2B342C'
TEXT = '#F2F6EE'
MUTED = '#899487'
ACID = '#B8F34A'
DANGER = '#FF786E'


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
        self.password = ''
        self.report = None
        self.tunnels = {}
        self.component_states = {}
        self.rows = []
        self.selected_id = None
        self.busy = False

        self.search = ft.TextField(
            hint_text='Поиск домена',
            prefix_icon=ft.Icons.SEARCH,
            border_radius=14,
            border_color=LINE,
            focused_border_color=ACID,
            bgcolor=PANEL,
            color=TEXT,
            dense=True,
            on_change=self.render_domains,
            expand=True,
        )
        self.source_filter = ft.Dropdown(
            value='all',
            width=185,
            border_radius=14,
            border_color=LINE,
            focused_border_color=ACID,
            bgcolor=PANEL,
            color=TEXT,
            dense=True,
            options=[
                ft.DropdownOption(key='all', text='Все источники'),
                ft.DropdownOption(key='chrome', text='Только Chrome'),
                ft.DropdownOption(key='desktop', text='Только Desktop'),
                ft.DropdownOption(key='rucens', text='Только rucens'),
            ],
            on_select=self.render_domains,
        )
        self.domain_list = ft.ListView(expand=True, spacing=8, padding=0)
        self.detail = ft.Column(expand=True, spacing=12)
        self.status_text = ft.Text('Локальная база', color=MUTED, size=12)
        self.progress = ft.ProgressBar(color=ACID, bgcolor=LINE, visible=False)
        self.root = ft.Column(expand=True, spacing=0)
        self.file_picker = ft.FilePicker()

    def configure_page(self):
        """Apply the desktop theme and render the first-run connection screen."""
        self.page.title = 'Keenetic · маршруты сайтов'
        self.page.bgcolor = BG
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 0
        self.page.window.width = 1080
        self.page.window.height = 720
        self.page.window.min_width = 850
        self.page.window.min_height = 580
        self.page.services.append(self.file_picker)
        self.page.add(self.root)
        self.render_login()

    def render_login(self, error=None):
        """Render a focused single-router connection and diagnostics screen."""
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
        login_progress = ft.ProgressBar(color=ACID, bgcolor=LINE, visible=False)

        async def connect(_event=None):
            login_progress.visible = True
            login_status.color = MUTED
            login_status.value = 'Проверяю SSH и Telnet…'
            self.page.update()
            try:
                profile = RouterProfile(
                    host=host.value or '',
                    user=user.value or '',
                    ssh_port=self.profile.ssh_port,
                    telnet_port=self.profile.telnet_port,
                ).validate()
                report = await asyncio.to_thread(
                    bootstrap_router,
                    profile,
                    password.value or '',
                    auto_enable_ssh=bool(auto_ssh.value),
                )
                selected = replace(profile, preferred_transport=report.transport or 'auto')
                save_profile(selected)
                self.profile = selected
                self.password = password.value or ''
                self.report = report
                self.tunnels = dict(report.tunnels)
                self.component_states = await asyncio.to_thread(self._inspect_components)
            except Exception as exception:
                login_progress.visible = False
                login_status.color = DANGER
                login_status.value = str(exception)
                self.page.update()
                return
            self.render_dashboard()
            self.reload_data()

        connect_button = ft.Button(
            'Подключиться',
            icon=ft.Icons.LINK,
            bgcolor=ACID,
            color=BG,
            height=46,
            on_click=connect,
        )
        card = ft.Container(
            width=520,
            padding=32,
            border_radius=22,
            bgcolor=PANEL,
            border=ft.Border.all(1, LINE),
            content=ft.Column(
                spacing=16,
                controls=[
                    ft.Container(
                        width=54,
                        height=54,
                        border_radius=16,
                        bgcolor=ACID,
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ft.Icons.ROUTER, color=BG, size=28),
                    ),
                    ft.Text('Подключить Keenetic', color=TEXT, size=28, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        'Приложение сначала проверит SSH. Если он выключен, подключится по Telnet, '
                        'запустит SSH и проверит повторный вход.',
                        color=MUTED,
                        size=13,
                    ),
                    host,
                    user,
                    password,
                    auto_ssh,
                    login_progress,
                    login_status,
                    connect_button,
                    ft.Text(
                        'Пароль хранится только до закрытия приложения.',
                        color=MUTED,
                        size=10,
                    ),
                ],
            ),
        )
        self.root.controls.append(
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                padding=28,
                content=ft.Column(
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text('ROUTE CONTROL', color=ACID, size=11, weight=ft.FontWeight.BOLD),
                        ft.Container(height=12),
                        card,
                    ],
                ),
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

    def render_dashboard(self):
        """Assemble the authenticated router dashboard."""
        self.root.controls.clear()
        self.root.controls.extend(
            [
                self._header(),
                self.progress,
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
        self.password = ''
        self.report = None
        self.tunnels = {}
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
        name = ft.TextField(label='Название', value=suggested)
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

    def _header(self):
        transport = (self.report.transport if self.report else 'offline').upper()
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=24, vertical=18),
            border=ft.Border(bottom=ft.BorderSide(1, LINE)),
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=38,
                        height=38,
                        border_radius=12,
                        bgcolor=ACID,
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ft.Icons.ROUTE, color=BG, size=21),
                    ),
                    ft.Column(
                        spacing=1,
                        controls=[
                            ft.Text(
                                f'KEENETIC · {self.profile.host} · {transport}',
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
                        'Обновить',
                        icon=ft.Icons.SYNC,
                        color=BG,
                        bgcolor=ACID,
                        elevation=0,
                        on_click=self.sync_all,
                    ),
                    ft.Button(
                        'VPN',
                        icon=ft.Icons.SHIELD_OUTLINED,
                        color=TEXT,
                        bgcolor=PANEL_ACTIVE,
                        elevation=0,
                        on_click=self.open_tunnel_dialog,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        icon_color=TEXT,
                        bgcolor=PANEL_ACTIVE,
                        tooltip='Добавить домен',
                        on_click=self.open_add_dialog,
                    ),
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
            width=500,
            padding=20,
            border=ft.Border(right=ft.BorderSide(1, LINE)),
            content=ft.Column(
                expand=True,
                controls=[
                    ft.Row(controls=[self.search, self.source_filter]),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text('ДОМЕНЫ', color=MUTED, size=10, weight=ft.FontWeight.BOLD),
                            ft.Text('Источник · маршруты', color=MUTED, size=10),
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

    def visible_rows(self):
        """Return rows matching the current text and provenance filters."""
        query = (self.search.value or '').strip().lower()
        source = self.source_filter.value or 'all'
        result = []
        for row in self.rows:
            sources = split_sources(row['sources'])
            if query and query not in row['domain'].lower():
                continue
            if source == 'rucens' and not any(item.startswith('rucens:') for item in sources):
                continue
            if source not in {'all', 'rucens'} and source not in sources:
                continue
            result.append(row)
        return result

    def render_domains(self, _event=None):
        """Rebuild the domain list without contacting the router."""
        self.domain_list.controls.clear()
        visible = self.visible_rows()
        if not visible:
            self.domain_list.controls.append(
                ft.Container(
                    padding=24,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text('Здесь пока пусто', color=MUTED),
                )
            )
        for row in visible:
            selected = row['id'] == self.selected_id
            badges = self.source_badges(row)
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
                            ft.Column(
                                expand=True,
                                spacing=5,
                                controls=[
                                    ft.Text(row['domain'], color=TEXT, size=14, weight=ft.FontWeight.BOLD),
                                    ft.Row(spacing=5, wrap=True, controls=badges),
                                ],
                            ),
                            ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                                spacing=1,
                                controls=[
                                    ft.Text(
                                        str(row['inventory_route_count'] + row['address_count']),
                                        color=TEXT,
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text('МАРШРУТОВ', color=MUTED, size=8),
                                ],
                            ),
                            ft.Icon(ft.Icons.CHEVRON_RIGHT, color=MUTED, size=17),
                        ]
                    ),
                )
            )
        self.page.update()

    def select_domain(self, event):
        """Select a row from the list and render its stored IP addresses."""
        self.selected_id = event.control.data
        self.render_domains()
        self.render_detail()

    def selected_row(self):
        """Return the current domain row, or ``None`` when nothing is selected."""
        return next((row for row in self.rows if row['id'] == self.selected_id), None)

    def render_detail(self):
        """Render provenance, timing and IP history for the selected domain."""
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

        addresses = domain_addresses(row['id'])
        inventory_routes = domain_inventory_routes(row['id'])
        sources = split_sources(row['sources'])
        actions = []
        if 'chrome' in sources:
            actions.append(
                ft.Button(
                    'Убрать метку Chrome',
                    icon=ft.Icons.TIMER_OFF,
                    color=TEXT,
                    bgcolor=PANEL_ACTIVE,
                    elevation=0,
                    on_click=self.release_chrome,
                )
            )
        actions.append(
            ft.Button(
                'Отключить домен',
                icon=ft.Icons.POWER_SETTINGS_NEW,
                color=DANGER,
                bgcolor='#2B1716',
                elevation=0,
                on_click=self.confirm_disable,
            )
        )
        ip_controls = [
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=9),
                border_radius=10,
                bgcolor=PANEL,
                border=ft.Border.all(1, LINE),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(address['address'], color=TEXT, font_family='monospace', size=13),
                        ft.Text('DNS · ' + address['last_seen_at'][0:16].replace('T', ' '), color=MUTED, size=10),
                    ],
                ),
            )
            for address in addresses
        ]
        ip_controls.extend(
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=9),
                border_radius=10,
                bgcolor=PANEL,
                border=ft.Border.all(1, LINE),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(route['network'], color=TEXT, font_family='monospace', size=13),
                        ft.Text(
                            f'{route["source_kind"]}:{route["source_name"]} · {route["interface"]}',
                            color=MUTED,
                            size=10,
                        ),
                    ],
                ),
            )
            for route in inventory_routes
        )
        if not ip_controls:
            ip_controls.append(ft.Text('IP ещё не фиксировались. Запусти обновление.', color=MUTED, size=12))

        self.detail.controls.extend(
            [
                ft.Text(row['domain'], color=TEXT, size=26, weight=ft.FontWeight.BOLD),
                ft.Row(spacing=6, wrap=True, controls=self.source_badges(row)),
                ft.Container(
                    padding=16,
                    border_radius=14,
                    bgcolor=PANEL,
                    border=ft.Border.all(1, LINE),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        controls=[
                            self._metric('ТУННЕЛЬ', row['tunnel']),
                            self._metric('CIDR', str(row['inventory_route_count'])),
                            self._metric('DNS IP', str(row['address_count'])),
                            self._metric('ПОСЛЕДНИЙ DNS', self.short_date(row['last_resolved_at'])),
                        ],
                    ),
                ),
                ft.Row(spacing=8, controls=actions),
                ft.Text('ИЗВЕСТНЫЕ IP И CIDR-МАРШРУТЫ', color=MUTED, size=10, weight=ft.FontWeight.BOLD),
                ft.ListView(expand=True, spacing=7, controls=ip_controls),
                ft.Text(
                    'При отключении удаляются только осиротевшие DNS-маршруты. Общие IP других доменов и rucens сохраняются.',
                    color=MUTED,
                    size=10,
                ),
            ]
        )
        self.page.update()

    @staticmethod
    def _metric(label, value):
        return ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2,
            controls=[ft.Text(label, color=MUTED, size=9), ft.Text(value, color=TEXT, size=13, weight=ft.FontWeight.BOLD)],
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
        """Toggle the global operation indicator and optional status text."""
        self.busy = value
        self.progress.visible = value
        if text:
            self.status_text.value = text
        self.page.update()

    async def sync_all(self, _event=None):
        """Run the shared synchronizer outside the UI event loop."""
        if self.busy:
            return
        await self.set_busy(True, 'Обновляю DNS и маршруты…')
        summary = await asyncio.to_thread(sync_domains)
        await self.set_busy(False, f'Добавлено {summary.added} · без изменений {summary.unchanged} · ошибок {summary.errors}')
        self.reload_data()

    def open_add_dialog(self, _event=None):
        """Open a compact dialog for registering a desktop-sourced domain."""
        if not self.tunnels:
            self._show_error('Сначала добавьте и подключите WireGuard-туннель')
            return
        default_tunnel = sorted(self.tunnels)[0]
        domain_field = ft.TextField(
            label='Домен',
            hint_text='example.com',
            autofocus=True,
            border_color=LINE,
            focused_border_color=ACID,
        )
        tunnel_field = ft.Dropdown(
            label='Туннель',
            value=default_tunnel,
            options=[
                ft.DropdownOption(key=short, text=f'{short} · {full}')
                for short, full in sorted(self.tunnels.items())
            ],
        )

        async def submit(_event=None):
            try:
                canonical, _ = add_managed_domain(domain_field.value, tunnel_field.value, source='desktop')
            except ValueError as error:
                domain_field.error = str(error)
                self.page.update()
                return
            self.page.pop_dialog()
            self.reload_data()
            row = next(item for item in self.rows if item['domain'] == canonical)
            await self.set_busy(True, f'Добавляю {canonical}…')
            summary = await asyncio.to_thread(sync_domains, [row])
            await self.set_busy(False, f'{canonical}: добавлено {summary.added}, ошибок {summary.errors}')
            self.reload_data()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Добавить домен'),
            content=ft.Column(tight=True, width=420, controls=[domain_field, tunnel_field]),
            actions=[
                ft.Button('Отмена', on_click=lambda _e: self.page.pop_dialog()),
                ft.Button('Добавить', bgcolor=ACID, color=BG, on_click=submit),
            ],
        )
        self.page.show_dialog(dialog)

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
                cleanup = await asyncio.to_thread(purge_domain_routes, row['domain'])
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
            cleanup = await asyncio.to_thread(purge_domain_routes, row['domain'])
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
