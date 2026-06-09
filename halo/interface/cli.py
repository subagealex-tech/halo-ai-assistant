import logging
import shlex
import sys
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from halo.core.engine import HALOEngine

log = logging.getLogger("halo.cli")

BANNER = r"""
[bold cyan]   _  _    ___    _     ___   [/bold cyan]
[bold cyan]  | || |  / _ \  | |   / _ \  [/bold cyan]
[bold cyan]  | || |_| | | | | |  | | | | [/bold cyan]
[bold cyan]  |__   _| |_| | | |__| |_| | [/bold cyan]
[bold cyan]     |_|  \___/  |_____\___/  [/bold cyan]
[bold cyan]                               [/bold cyan]
"""


class HUD:
    def __init__(self) -> None:
        self.console = Console()

    def print_banner(self) -> None:
        self.console.print(BANNER)
        subtitle = Text("Heuristic Automated Logic Operator  •  v0.1.0", style="dim italic")
        self.console.print(subtitle, justify="center")
        self.console.print()

    def show_thinking(self, message: str) -> None:
        lines = message.strip().split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped:
                self.console.print(f"  [dim]⏳ {stripped}[/dim]")

    def show_tool_call(self, tool_name: str, args: dict) -> None:
        args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        self.console.print(f"  [yellow]⚡ {tool_name}({args_str})[/yellow]")

    def show_response(self, content: str) -> None:
        if not content:
            return
        md = Markdown(content.strip())
        panel = Panel(md, border_style="cyan", title="[bold]H.A.L.O.[/bold]", title_align="left")
        self.console.print(panel)

    def show_error(self, msg: str) -> None:
        self.console.print(f"  [red]✖ {msg}[/red]")

    def show_status(self, msg: str) -> None:
        self.console.print(f"  [dim]{msg}[/dim]")

    def divider(self) -> None:
        self.console.print(Rule(style="dim"))


def run_cli(engine: HALOEngine) -> None:
    hud = HUD()
    hud.print_banner()
    hud.show_status("System online. Awaiting your command, Boss.")
    hud.divider()

    while True:
        try:
            user_input = Prompt.ask("[bold green]You[/bold green]")
        except (KeyboardInterrupt, EOFError):
            hud.divider()
            hud.show_status("Shutting down. Until next time, Boss.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit", "/q"):
            hud.divider()
            hud.show_status("Disconnecting. Good hunting, Boss.")
            break

        if user_input.lower() == "/clear":
            engine.memory.clear()
            hud.show_status("Conversation memory wiped.")
            continue

        if user_input.lower() == "/help":
            _show_help(hud)
            continue

        hud.divider()

        def stream_handler(chunk: str) -> None:
            pass

        try:
            response = engine.process_message(user_input, stream_handler=stream_handler)
            hud.show_response(response)
        except Exception as e:
            log.exception("Engine error")
            hud.show_error(f"Engine fault: {e}")

        hud.divider()


def _show_help(hud: HUD) -> None:
    table = Table(show_header=False, border_style="dim")
    table.add_column("Command", style="bold")
    table.add_column("Description")
    table.add_row("/exit, /quit, /q", "Shut down H.A.L.O.")
    table.add_row("/clear", "Wipe conversation memory")
    table.add_row("/help", "Show this help screen")
    hud.console.print(table)
