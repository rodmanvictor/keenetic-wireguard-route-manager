"""First-run diagnostics and safe KeeneticOS transport bootstrap.

The onboarding flow prefers SSH, may enable the SSH service through Telnet,
and keeps Telnet as an explicit fallback.  Installing KeeneticOS components is
separate because ``components commit`` can update firmware and reboot the
router.
"""

from dataclasses import dataclass, field
import socket
import time

from keenetic_router.core.profiles import RouterProfile
from keenetic_router.core.router import (
    configure_runtime_connection,
    create_ssh_client,
    create_telnet_client,
    discover_wireguard_tunnel_details,
)


@dataclass(frozen=True)
class DiagnosticStep:
    """One user-facing result from router onboarding."""

    key: str
    status: str
    detail: str


@dataclass
class BootstrapReport:
    """Outcome of one first-run connection attempt.

    Attributes:
        profile: Validated router profile used for the attempt.
        transport: Working transport, or ``None`` when onboarding failed.
        ssh_enabled: Whether a real SSH login succeeded.
        telnet_fallback: Whether subsequent operations must use Telnet.
        tunnels: Mapping such as ``wg1 -> Wireguard1`` discovered live.
        tunnel_labels: User-assigned interface descriptions keyed by ``wgN``.
        tunnel_statuses: Live ``up`` or ``down`` state keyed by ``wgN``.
        steps: Ordered diagnostic messages safe to show in CLI and GUI.
    """

    profile: RouterProfile
    transport: str | None = None
    ssh_enabled: bool = False
    telnet_fallback: bool = False
    tunnels: dict[str, str] = field(default_factory=dict)
    tunnel_labels: dict[str, str] = field(default_factory=dict)
    tunnel_statuses: dict[str, str] = field(default_factory=dict)
    steps: list[DiagnosticStep] = field(default_factory=list)

    @property
    def ready(self):
        """Return whether at least one authenticated transport is available."""
        return self.transport in {'ssh', 'telnet'}


@dataclass(frozen=True)
class ComponentState:
    """Installed and available state for one KeeneticOS component."""

    name: str
    installed: bool
    queued: bool
    available_version: str | None = None
    installed_version: str | None = None


@dataclass(frozen=True)
class ComponentInstallResult:
    """Result of queuing and committing KeeneticOS component changes."""

    requested: tuple[str, ...]
    queued: tuple[str, ...]
    skipped: tuple[str, ...]
    errors: tuple[str, ...]
    reboot_expected: bool


class RouterBootstrapError(RuntimeError):
    """Raised when neither SSH nor Telnet can authenticate to the router."""


def _error_text(error):
    """Return a concise exception message that never includes credentials."""
    name = type(error).__name__
    detail = str(error).strip()
    return f'{name}: {detail}' if detail else name


def port_is_open(host, port, timeout=1.0):
    """Return whether a TCP connection can be established to an address."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _open_ssh(profile, password):
    """Open an explicit SSH connection without touching global runtime state."""
    return create_ssh_client(
        host=profile.host,
        port=profile.ssh_port,
        user=profile.user,
        password=password,
        command_wait=1.0,
    )


def _open_telnet(profile, password):
    """Open an explicit Telnet connection without touching global state."""
    return create_telnet_client(
        host=profile.host,
        port=profile.telnet_port,
        user=profile.user,
        password=password,
        send_char_delay=0.02,
        command_wait=0.45,
    )


def _discover_and_close(client):
    """Discover WireGuard interfaces and always close the temporary client."""
    try:
        details = discover_wireguard_tunnel_details(client)
        return (
            {short: tunnel.interface for short, tunnel in details.items()},
            {short: tunnel.display_name for short, tunnel in details.items()},
            {short: tunnel.status for short, tunnel in details.items()},
        )
    finally:
        client.disconnect()


def bootstrap_router(profile, password, *, auto_enable_ssh=True, ssh_wait=20):
    """Authenticate, enable SSH through Telnet when possible, and select transport.

    Args:
        profile: Non-secret router connection profile.
        password: Administrator password retained only for the current process.
        auto_enable_ssh: Run ``service ssh`` through Telnet after SSH failure.
        ssh_wait: Seconds to wait for a newly started SSH service.

    Returns:
        :class:`BootstrapReport` with a live-tested transport and tunnel list.

    Raises:
        RouterBootstrapError: When neither transport accepts the connection.

    Side effects:
        May enable and save the SSH service.  On success, configures the shared
        in-memory client factory for subsequent CLI/desktop operations.
    """
    profile = profile.validate()
    if not password:
        raise RouterBootstrapError('Пароль не введён')
    report = BootstrapReport(profile=profile)

    try:
        ssh = _open_ssh(profile, password)
    except Exception as error:
        report.steps.append(DiagnosticStep('ssh-login', 'warning', f'SSH недоступен: {_error_text(error)}'))
    else:
        report.transport = 'ssh'
        report.ssh_enabled = True
        report.steps.append(DiagnosticStep('ssh-login', 'ok', f'SSH подключён на порту {profile.ssh_port}'))
        report.tunnels, report.tunnel_labels, report.tunnel_statuses = _discover_and_close(ssh)
        configure_runtime_connection(
            profile.host,
            profile.user,
            password,
            transport='ssh',
            ssh_port=profile.ssh_port,
            telnet_port=profile.telnet_port,
        )
        return report

    try:
        telnet = _open_telnet(profile, password)
        probe = telnet.command('show interface')
        if not probe.strip():
            raise RouterBootstrapError('Telnet не вернул приглашение KeeneticOS')
    except Exception as error:
        report.steps.append(
            DiagnosticStep('telnet-login', 'error', f'Telnet недоступен: {_error_text(error)}')
        )
        raise RouterBootstrapError(
            'Не удалось подключиться ни по SSH, ни по Telnet. Проверь адрес, логин, пароль '
            'и доступ к управлению из этой сети.'
        ) from error

    report.steps.append(DiagnosticStep('telnet-login', 'ok', f'Telnet подключён на порту {profile.telnet_port}'))
    if auto_enable_ssh:
        start_output = telnet.command('service ssh')
        save_output = telnet.command('system configuration save')
        if 'error' in start_output.lower():
            report.steps.append(
                DiagnosticStep(
                    'ssh-enable',
                    'warning',
                    'KeeneticOS не запустил SSH. Вероятно, компонент SSH не установлен.',
                )
            )
        elif 'error' in save_output.lower():
            report.steps.append(
                DiagnosticStep('ssh-enable', 'warning', 'SSH запущен, но сохранение настройки не подтверждено')
            )
        else:
            report.steps.append(DiagnosticStep('ssh-enable', 'ok', 'SSH включён через Telnet и сохранён'))

        deadline = time.monotonic() + max(1, ssh_wait)
        while time.monotonic() < deadline:
            # A separate TCP port probe immediately before Paramiko caused
            # Dropbear on real Keenetic hardware to reset the actual login.
            # Only a complete authenticated session counts as verification.
            try:
                ssh = _open_ssh(profile, password)
            except Exception:
                time.sleep(1.0)
                continue
            telnet.disconnect()
            report.transport = 'ssh'
            report.ssh_enabled = True
            report.steps.append(DiagnosticStep('ssh-verify', 'ok', 'Повторный вход по SSH подтверждён'))
            report.tunnels, report.tunnel_labels, report.tunnel_statuses = _discover_and_close(ssh)
            configure_runtime_connection(
                profile.host,
                profile.user,
                password,
                transport='ssh',
                ssh_port=profile.ssh_port,
                telnet_port=profile.telnet_port,
            )
            return report

    report.transport = 'telnet'
    report.telnet_fallback = True
    details = discover_wireguard_tunnel_details(telnet)
    report.tunnels = {short: tunnel.interface for short, tunnel in details.items()}
    report.tunnel_labels = {short: tunnel.display_name for short, tunnel in details.items()}
    report.tunnel_statuses = {short: tunnel.status for short, tunnel in details.items()}
    telnet.disconnect()
    report.steps.append(
        DiagnosticStep(
            'fallback',
            'warning',
            'Работаем через медленный Telnet. Установи компонент «Сервер SSH» или запусти setup с установкой компонентов.',
        )
    )
    configure_runtime_connection(
        profile.host,
        profile.user,
        password,
        transport='telnet',
        ssh_port=profile.ssh_port,
        telnet_port=profile.telnet_port,
    )
    return report


def parse_component_states(output):
    """Parse ``components list`` output into states keyed by component name."""
    states = {}
    for block in output.split('component:')[1:]:
        values = {}
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if ': ' not in line:
                continue
            key, value = line.split(': ', 1)
            if key in {'name', 'installed', 'queued', 'version'} and key not in values:
                values[key] = value.strip()
        name = values.get('name')
        if not name:
            continue
        states[name] = ComponentState(
            name=name,
            installed='installed' in values,
            queued=values.get('queued') == 'yes',
            available_version=values.get('version'),
            installed_version=values.get('installed'),
        )
    return states


def inspect_components(client):
    """Return all KeeneticOS component states using an authenticated client.

    Side effects:
        Enters and leaves the non-mutating ``components`` CLI context.
    """
    client.command('components')
    try:
        return parse_component_states(client.command('list', timeout=180))
    finally:
        client.command('exit')


def install_components(client, names):
    """Queue missing KeeneticOS components and commit the firmware change.

    Args:
        client: Authenticated SSH or Telnet client.
        names: Component identifiers such as ``ssh`` and ``wireguard``.

    Returns:
        :class:`ComponentInstallResult` describing the submitted change.

    Side effects:
        Runs ``components install`` followed by ``commit``.  KeeneticOS may
        download firmware, interrupt the current connection, and reboot.  The
        caller must obtain explicit user confirmation before calling.
    """
    requested = tuple(dict.fromkeys(str(name).strip() for name in names if str(name).strip()))
    states = inspect_components(client)
    skipped = tuple(name for name in requested if states.get(name) and states[name].installed)
    missing = tuple(name for name in requested if name not in skipped)
    unavailable = tuple(name for name in missing if name not in states)
    queued = []
    errors = [f'Компонент {name} недоступен для этой модели или версии KeeneticOS' for name in unavailable]
    installable = tuple(name for name in missing if name in states)
    if not installable:
        return ComponentInstallResult(requested, (), skipped, tuple(errors), False)

    client.command('components')
    try:
        for name in installable:
            output = client.command(f'install {name}')
            if 'error' in output.lower():
                errors.append(f'{name}: KeeneticOS отклонил установку')
            else:
                queued.append(name)
        if queued:
            try:
                output = client.command('commit', timeout=240)
                if 'error' in output.lower():
                    errors.append('KeeneticOS не применил выбранные компоненты')
            except (EOFError, OSError, socket.error):
                # Connection loss is expected once a component firmware commit starts.
                pass
    finally:
        try:
            client.command('exit')
        except Exception:
            pass
    return ComponentInstallResult(
        requested=requested,
        queued=tuple(queued),
        skipped=skipped,
        errors=tuple(errors),
        reboot_expected=bool(queued and not errors),
    )
