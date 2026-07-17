"""Command line interface: ipace-obd scan / battery / dtc-read / dtc-clear / raw / monitor."""

from __future__ import annotations

import asyncio
import csv
import functools
import sys
import time
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .ble_transport import scan_all, scan_for_adapters
from .dtc import clear_all, clear_legacy_dtcs, describe_status, read_ecu_dtcs, read_legacy_dtcs, scan_ecus_for_dtcs
from .pids.ecus import ECUS, PRIORITY_ECUS
from .pids.ipace_battery import BATTERY_PIDS, BATTERY_PIDS_BY_KEY
from .session import IPaceSession

console = Console()


class CliError(RuntimeError):
    """Raised to show a clean, friendly error message (no Python traceback)."""


def _run(coro):
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
    except CliError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except TimeoutError as exc:
        console.print(f"[red]Timed out talking to the adapter:[/red] {exc}")
        console.print("[dim]The car may be asleep, out of range, or another app/phone is "
                      "already connected to the dongle.[/dim]")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - translate low-level BLE errors to something readable
        message = str(exc)
        lowered = message.lower()
        if "bluez" in lowered or "dbus" in lowered:
            console.print("[red]No usable Bluetooth stack was found on this computer.[/red]")
            console.print("[dim]On Linux, make sure BlueZ (bluetoothd) is installed and running: "
                          "'systemctl status bluetooth'. On Windows/macOS, make sure Bluetooth is "
                          "turned on in system settings.[/dim]")
        elif "winrt" in lowered or "not supported" in lowered:
            console.print(f"[red]Bluetooth backend error:[/red] {message}")
            console.print("[dim]Make sure Bluetooth is enabled on this computer.[/dim]")
        elif "was not found" in lowered or "device not found" in lowered or "not found" in lowered:
            console.print(f"[red]Could not find the adapter:[/red] {message}")
            console.print("[dim]Double-check the --address with 'ipace-obd scan', and make sure the "
                          "dongle is plugged in and the car is awake.[/dim]")
        else:
            console.print(f"[red]Unexpected error:[/red] {message}")
            console.print("[dim]Re-run with -v for a full debug log / traceback.[/dim]")
        if "-v" in sys.argv or "--verbose" in sys.argv:
            raise
        sys.exit(1)


def async_command(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return _run(f(*args, **kwargs))

    return wrapper


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging (BLE + protocol traffic).")
def main(verbose: bool):
    """ipace-obd: read HV battery data and diagnostic trouble codes from a Jaguar I-PACE
    over a BLE ELM327 adapter (e.g. Veepeak OBDCheck BLE).

    Run this on the computer that is physically near the car and has Bluetooth - it
    cannot run against a car connected to a *different* machine.
    """
    import logging

    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)


@main.command()
@click.option("--timeout", default=8.0, show_default=True, help="BLE scan duration in seconds.")
@click.option("--all", "show_all", is_flag=True, help="List every nearby BLE device, not just likely OBD adapters.")
def scan(timeout: float, show_all: bool):
    """Scan for nearby BLE OBD-II adapters (e.g. your Veepeak dongle)."""

    async def _scan():
        console.print(f"Scanning for BLE devices for {timeout:.0f}s... (make sure the Veepeak is plugged into the "
                      "car's OBD-II port and the car is not asleep)")
        adapters = await (scan_all(timeout) if show_all else scan_for_adapters(timeout))
        if not adapters:
            console.print("[yellow]No matching devices found.[/yellow] Try --all to list every BLE device nearby, "
                           "or move closer to the car / wake it up (press brake or open a door).")
            return
        table = Table(title="Discovered BLE devices")
        table.add_column("Name")
        table.add_column("Address")
        table.add_column("RSSI")
        for a in sorted(adapters, key=lambda x: -(x.rssi or -999)):
            table.add_row(a.name, a.address, str(a.rssi))
        console.print(table)
        console.print("\nUse the Address above with --address on other commands, e.g.:\n"
                      f"  ipace-obd battery --address {adapters[0].address}")

    _run(_scan())


def _address_option(f):
    return click.option(
        "--address",
        required=True,
        help="BLE address (MAC on Linux/Windows, UUID on macOS) of the OBD adapter. Run 'ipace-obd scan' to find it.",
    )(f)


@main.command()
@_address_option
def info(address: str):
    """Connect and print adapter identification + car battery voltage (sanity check)."""

    async def _info():
        console.print(f"Connecting to {address} ...")
        async with await IPaceSession.connect_to(address) as session:
            console.print("[green]Connected.[/green]")
            console.print(f"Adapter ID: {session.info.id_string}")
            console.print(f"Adapter-reported car voltage (12V system): {session.info.voltage}")

    _run(_info())


@main.command()
@_address_option
@click.option("--csv", "csv_path", type=click.Path(dir_okay=False), help="Append this reading as a row to a CSV log file.")
@click.option("--only", multiple=True, help="Only read these PID keys (repeatable). See 'ipace-obd list-pids'.")
def battery(address: str, csv_path: Optional[str], only: tuple[str, ...]):
    """Read all known HV battery PIDs from the BECM (and a couple of related modules)."""

    async def _battery():
        pids = [BATTERY_PIDS_BY_KEY[k] for k in only] if only else BATTERY_PIDS
        async with await IPaceSession.connect_to(address) as session:
            console.print("[green]Connected.[/green] Reading battery PIDs...\n")
            readings = await session.read_all_battery_pids(pids)

            table = Table(title="Jaguar I-PACE Battery Data")
            table.add_column("Key")
            table.add_column("Name")
            table.add_column("Value")
            table.add_column("Verified?")
            table.add_column("Notes")
            for r in readings:
                verified = "yes" if r.pid.verified else "[yellow]unconfirmed[/yellow]"
                table.add_row(r.pid.key, r.pid.name, r.formatted, verified, r.pid.notes)
            console.print(table)

            if csv_path:
                _append_csv(csv_path, readings)
                console.print(f"\nAppended reading to {csv_path}")

    _run(_battery())


def _append_csv(path: str, readings) -> None:
    import os

    fieldnames = ["timestamp"] + [r.pid.key for r in readings]
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        row = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
        for r in readings:
            row[r.pid.key] = r.value if r.value is not None else ""
        writer.writerow(row)


@main.command()
@_address_option
@click.option("--interval", default=5.0, show_default=True, help="Seconds between readings.")
@click.option("--csv", "csv_path", type=click.Path(dir_okay=False), required=True, help="CSV file to append readings to.")
@click.option("--only", multiple=True, help="Only log these PID keys (repeatable).")
def monitor(address: str, interval: float, csv_path: str, only: tuple[str, ...]):
    """Continuously poll battery PIDs and log them to a CSV file (Ctrl-C to stop)."""

    async def _monitor():
        pids = [BATTERY_PIDS_BY_KEY[k] for k in only] if only else BATTERY_PIDS
        async with await IPaceSession.connect_to(address) as session:
            console.print(f"[green]Connected.[/green] Logging to {csv_path} every {interval:.0f}s. Press Ctrl-C to stop.")
            try:
                while True:
                    readings = await session.read_all_battery_pids(pids)
                    _append_csv(csv_path, readings)
                    soc = next((r for r in readings if r.pid.key == "soc_avg"), None)
                    volt = next((r for r in readings if r.pid.key == "pack_voltage"), None)
                    console.print(
                        f"{time.strftime('%H:%M:%S')}  SOC={soc.formatted if soc else 'n/a'}  "
                        f"Voltage={volt.formatted if volt else 'n/a'}"
                    )
                    await asyncio.sleep(interval)
            except KeyboardInterrupt:
                console.print("\nStopped.")

    _run(_monitor())


@main.command(name="list-pids")
def list_pids():
    """List all known battery PID keys/names (for use with --only)."""
    table = Table(title="Known battery PIDs")
    table.add_column("Key")
    table.add_column("Name")
    table.add_column("ECU")
    table.add_column("PID (Mode+DID)")
    table.add_column("Verified?")
    for p in BATTERY_PIDS:
        table.add_row(p.key, p.name, p.ecu.name, p.request_hex, "yes" if p.verified else "unconfirmed")
    console.print(table)


@main.group(name="dtc")
def dtc_group():
    """Read or clear diagnostic trouble codes (fault codes)."""


@dtc_group.command(name="read")
@_address_option
@click.option(
    "--scope",
    type=click.Choice(["legacy", "modules", "all"]),
    default="all",
    show_default=True,
    help="'legacy' = generic OBD-II broadcast codes only; 'modules' = per-ECU UDS scan "
    "(BECM/ABS/BCM/etc.); 'all' = both.",
)
@click.option(
    "--ecus",
    default="priority",
    show_default=True,
    help="'priority' (battery + common modules), 'all' (every known module - slower), "
    "or a comma-separated list of module names (e.g. BECM,ABS,BCM).",
)
def dtc_read(address: str, scope: str, ecus: str):
    """Read fault codes. By default checks both the generic OBD-II layer and scans the
    key body/battery/chassis modules directly (like a dealer-level 'scan all modules')."""

    if ecus == "priority":
        ecu_names = PRIORITY_ECUS
    elif ecus == "all":
        ecu_names = list(ECUS.keys())
    else:
        ecu_names = [n.strip().upper() for n in ecus.split(",") if n.strip()]
        unknown = [n for n in ecu_names if n not in ECUS]
        if unknown:
            raise click.BadParameter(f"Unknown ECU name(s): {', '.join(unknown)}. Known: {', '.join(ECUS)}")

    async def _read():
        async with await IPaceSession.connect_to(address) as session:
            console.print("[green]Connected.[/green]\n")

            if scope in ("legacy", "all"):
                console.print("[bold]Generic OBD-II (legacy) codes:[/bold]")
                any_found = False
                for category in ("stored", "pending", "permanent"):
                    try:
                        dtcs = await read_legacy_dtcs(session.elm, category)
                    except Exception as exc:  # noqa: BLE001
                        console.print(f"  {category}: [red]error - {exc}[/red]")
                        continue
                    if dtcs:
                        any_found = True
                        console.print(f"  {category}: " + ", ".join(d.code for d in dtcs))
                    else:
                        console.print(f"  {category}: none")
                if not any_found:
                    console.print("  [dim](no generic OBD-II codes found)[/dim]")
                console.print()

            if scope in ("modules", "all"):
                console.print(f"[bold]Per-module UDS scan[/bold] ({len(ecu_names)} module(s)):")
                results = await scan_ecus_for_dtcs(session.elm, ecu_names)
                table = Table()
                table.add_column("Module")
                table.add_column("Code")
                table.add_column("Status flags")
                any_found = False
                for res in results:
                    if res.error:
                        table.add_row(res.ecu.name, "-", f"[red]{res.error}[/red]")
                        continue
                    if not res.dtcs:
                        continue
                    any_found = True
                    for d in res.dtcs:
                        table.add_row(res.ecu.name, d.code, describe_status(d.status))
                console.print(table)
                if not any_found:
                    console.print("  [dim](no module fault codes found on the scanned modules)[/dim]")

    _run(_read())


@dtc_group.command(name="clear")
@_address_option
@click.option(
    "--ecus",
    default="priority",
    show_default=True,
    help="'priority', 'all', or a comma-separated list of module names to clear codes on "
    "(in addition to the generic OBD-II layer, which is always cleared).",
)
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def dtc_clear(address: str, ecus: str, yes: bool):
    """Clear (reset) fault codes on the generic OBD-II layer and the given modules.

    WARNING: this resets stored fault memory - if the underlying condition is still
    present the code(s) will likely return. Clearing does not fix anything by itself.
    """
    if ecus == "priority":
        ecu_names = PRIORITY_ECUS
    elif ecus == "all":
        ecu_names = list(ECUS.keys())
    else:
        ecu_names = [n.strip().upper() for n in ecus.split(",") if n.strip()]
        unknown = [n for n in ecu_names if n not in ECUS]
        if unknown:
            raise click.BadParameter(f"Unknown ECU name(s): {', '.join(unknown)}. Known: {', '.join(ECUS)}")

    if not yes:
        click.confirm(
            f"This will clear fault codes on the generic OBD-II layer plus {len(ecu_names)} "
            f"module(s) ({', '.join(ecu_names)}). Continue?",
            abort=True,
        )

    async def _clear():
        async with await IPaceSession.connect_to(address) as session:
            console.print("[green]Connected.[/green] Clearing DTCs...")
            results = await clear_all(session.elm, ecu_names)
            table = Table()
            table.add_column("Target")
            table.add_column("Adapter reply")
            for target, reply in results.items():
                table.add_row(target, reply)
            console.print(table)

    _run(_clear())


@main.command()
@_address_option
@click.argument("header")
@click.argument("payload_hex")
def raw(address: str, header: str, payload_hex: str):
    """Send a raw request to a given CAN header, e.g.:

    \b
      ipace-obd raw --address AA:BB:CC:DD:EE:FF 7E4 22490F
    """

    async def _raw():
        async with await IPaceSession.connect_to(address) as session:
            reply = await session.elm.request(header, payload_hex)
            console.print(reply)

    _run(_raw())


if __name__ == "__main__":
    main()
