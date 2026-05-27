from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import click
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scen_trace import __version__
from scen_trace.providers.loader import ProviderNotInstalledError, get_provider
from scen_trace.runner import RunResult, TurnTrace, run_scenario, write_trace
from scen_trace.validator import format_validation_error, load_scenario

console = Console()


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="scenetrace")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """ScenTrace — scenario-based regression testing for multi-agent AI workflows."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.option("--dir", "target_dir", default=".scenetrace", help="Target directory for scaffolding")
def init(target_dir: str) -> None:
    """Scaffold a new ScenTrace project with example scenario and config."""
    from scen_trace.scaffold import scaffold_project

    target = Path(target_dir)
    created, skipped = scaffold_project(target)

    if created:
        console.print(Panel(
            "[bold green]Project scaffolded![/bold green]\n\n"
            + "\n".join(f"  [green]+[/green] {f}" for f in created)
            + ("\n" + "\n".join(f"  [yellow]~[/yellow] {f} (exists, skipped)" for f in skipped) if skipped else "")
            + "\n\n[bold]Next steps:[/bold]\n"
            f"  1. [cyan]scenetrace validate {target}/example_scenario.yaml[/cyan]\n"
            f"  2. [cyan]scenetrace run {target}/example_scenario.yaml --provider mock[/cyan]\n"
            "  3. [cyan]scenetrace report <trace.json>[/cyan]",
            title="ScenTrace Init",
            border_style="blue",
        ))
    else:
        console.print(Panel(
            "[yellow]All files already exist. Nothing created.[/yellow]\n\n"
            + "\n".join(f"  [yellow]~[/yellow] {f}" for f in skipped),
            title="ScenTrace Init",
            border_style="yellow",
        ))


@cli.command()
@click.argument("path", type=click.Path(exists=True))
def validate(path: str) -> None:
    """Validate a scenario YAML file against the schema."""
    try:
        scenario = load_scenario(Path(path))
        console.print(f"[green]Scenario '{scenario.scenario_id}' is valid.[/green]")
    except ValidationError as e:
        console.print(f"[red]Schema Validation Error:[/red]\n{format_validation_error(e)}")
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--provider", "-p", default=None, help="Provider name (mock, openai)")
@click.option("--model", "-m", default=None, help="Model name override")
@click.option("--max-turns", type=int, default=None, help="Maximum turns to execute")
@click.option("--stop-on-error", is_flag=True, help="Stop on provider errors")
@click.option("--stop-on-fail", is_flag=True, help="Stop on first check failure")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output trace file path (.json or .jsonl)")
@click.option("--track", is_flag=True, help="Track run metrics in local analytics DB")
@click.option("--analytics-dir", default=".scenetrace", help="Analytics DB directory")
def run(path: str, provider: str | None, model: str | None, max_turns: int | None,
        stop_on_error: bool, stop_on_fail: bool, output: str | None,
        track: bool, analytics_dir: str) -> None:
    """Run a scenario and capture execution traces."""
    try:
        scenario = load_scenario(Path(path))
    except ValidationError as e:
        console.print(f"[red]Schema Validation Error:[/red]\n{format_validation_error(e)}")
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    provider_name = provider or scenario.model_config_.provider
    if model:
        scenario.model_config_.model_name = model

    try:
        prov = get_provider(provider_name)
    except ProviderNotInstalledError as e:
        console.print(Panel(str(e), title="Missing Provider", border_style="yellow"))
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    def on_turn(trace: TurnTrace) -> None:
        status_icon = "[green]✓[/green]" if trace.status == "success" else "[red]✗[/red]"
        console.print(f"  {status_icon} Turn {trace.turn_index + 1}: {trace.agent_name} ({trace.duration_ms:.0f}ms)")
        for cr in trace.check_results:
            cr_icon = "[green]✓[/green]" if cr["passed"] else "[red]✗[/red]"
            console.print(f"    {cr_icon} {cr['check_id']}: {cr['message']}")

    console.print(f"\n[bold]Running scenario:[/bold] {scenario.scenario_id}")
    console.print(f"[dim]Provider: {provider_name} | Model: {scenario.model_config_.model_name}[/dim]\n")

    try:
        result = run_scenario(
            scenario=scenario,
            provider=prov,
            max_turns=max_turns,
            stop_on_error=stop_on_error,
            stop_on_fail=stop_on_fail,
            on_turn_complete=on_turn,
            scenario_dir=Path(path).parent,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        sys.exit(1)

    _print_summary(result, provider_name)

    if output:
        write_trace(result, Path(output))
        console.print(f"\n[dim]Trace saved to: {output}[/dim]")

    if track:
        _track_run(result, output, analytics_dir)

    if result.status != "passed":
        sys.exit(1)


def _track_run(result: RunResult, output: str | None, analytics_dir: str) -> None:
    from scen_trace.analytics import AnalyticsDB
    from scen_trace.report import TraceData

    db = AnalyticsDB(analytics_dir=Path(analytics_dir))
    try:
        db.init()
        trace_data = TraceData(
            scenario_id=result.scenario_id,
            status=result.status,
            started_at=result.started_at,
            finished_at=result.finished_at,
            total_duration_ms=result.total_duration_ms,
            total_input_tokens=result.total_input_tokens,
            total_output_tokens=result.total_output_tokens,
            estimated_cost=result.estimated_cost,
            checks_passed=result.checks_passed,
            checks_failed=result.checks_failed,
            metadata=result.metadata,
            turns=[t.to_dict() for t in result.turns],
        )
        trace_path = Path(output) if output else Path(f"trace_{result.scenario_id}.json")
        db.ingest_run(trace_path, trace_data=trace_data)
        console.print(f"[dim]Run tracked in analytics DB ({analytics_dir}/analytics.db)[/dim]")
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to track run: {e}[/yellow]")
    finally:
        db.close()


def _print_summary(result: RunResult, provider_name: str) -> None:
    status_color = "green" if result.status == "passed" else "red"
    badge = f"[{status_color}]{result.status.upper()}[/{status_color}]"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")
    table.add_row("Status", badge)
    table.add_row("Provider", f"[bold]{provider_name}[/bold]")
    table.add_row("Turns", f"{len(result.turns)}")
    table.add_row("Duration", f"{result.total_duration_ms:.0f}ms")
    table.add_row("Tokens", f"{result.total_input_tokens} in / {result.total_output_tokens} out")
    table.add_row("Est. Cost", f"${result.estimated_cost:.6f}")
    if result.checks_passed + result.checks_failed > 0:
        table.add_row("Checks", f"{result.checks_passed} passed / {result.checks_failed} failed")

    console.print(Panel(table, title=f"[bold]{result.scenario_id}[/bold]", border_style=status_color))


@cli.command()
@click.argument("trace_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
@click.option("--format", "fmt", type=click.Choice(["html", "md"]), default="html", help="Report format (html or md)")
@click.option("--open", "open_browser", is_flag=True, help="Open report in browser")
def report(trace_path: str, output: str | None, fmt: str, open_browser: bool) -> None:
    """Generate an HTML or Markdown report from a trace file."""
    from scen_trace.report import generate_markdown_report, generate_report, load_trace

    trace_file = Path(trace_path)
    try:
        trace_data = load_trace(trace_file)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    ext = ".md" if fmt == "md" else ".html"
    if output:
        out_path = Path(output)
    else:
        out_path = trace_file.with_name(trace_file.stem + f"_report{ext}")

    content = generate_markdown_report(trace_data) if fmt == "md" else generate_report(trace_data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)

    console.print(f"[green]Report generated:[/green] {out_path}")

    if open_browser and fmt == "html":
        webbrowser.open(f"file://{out_path.resolve()}")


@cli.group()
def baseline() -> None:
    """Manage baseline traces for regression detection."""


@baseline.command("init")
@click.option("--dir", "baselines_dir", default=".scenetrace", help="Baselines directory")
def baseline_init(baselines_dir: str) -> None:
    """Initialize the baseline registry."""
    from scen_trace.baselines import BaselineRegistry

    registry = BaselineRegistry(baselines_dir=Path(baselines_dir))
    registry.init()
    console.print(f"[green]Baseline registry initialized at {baselines_dir}/[/green]")
    registry.close()


@baseline.command("save")
@click.argument("trace_path", type=click.Path(exists=True))
@click.option("--tag", "-t", required=True, help="Tag name for this baseline")
@click.option("--force", is_flag=True, help="Overwrite existing baseline with same tag")
@click.option("--dir", "baselines_dir", default=".scenetrace", help="Baselines directory")
def baseline_save(trace_path: str, tag: str, force: bool, baselines_dir: str) -> None:
    """Save a trace as a baseline with a tag."""
    from scen_trace.baselines import BaselineRegistry

    registry = BaselineRegistry(baselines_dir=Path(baselines_dir))
    try:
        entry = registry.save(Path(trace_path), tag, force=force)
        console.print(Panel(
            f"[green]Baseline saved![/green]\n\n"
            f"  Tag: [bold]{entry.tag}[/bold]\n"
            f"  Scenario: {entry.scenario_id}\n"
            f"  Status: {entry.status}\n"
            f"  Cost: ${entry.estimated_cost:.6f}\n"
            f"  Duration: {entry.total_duration_ms:.0f}ms\n"
            f"  Hash: {entry.trace_hash}",
            title="Baseline Saved",
            border_style="green",
        ))
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    finally:
        registry.close()


@baseline.command("list")
@click.option("--dir", "baselines_dir", default=".scenetrace", help="Baselines directory")
def baseline_list(baselines_dir: str) -> None:
    """List all saved baselines."""
    from scen_trace.baselines import BaselineRegistry

    registry = BaselineRegistry(baselines_dir=Path(baselines_dir))
    entries = registry.list_baselines()
    registry.close()

    if not entries:
        console.print("[yellow]No baselines saved yet.[/yellow]")
        return

    table = Table(title="Saved Baselines")
    table.add_column("Tag", style="bold cyan")
    table.add_column("Scenario")
    table.add_column("Status")
    table.add_column("Cost")
    table.add_column("Duration")
    table.add_column("Checks")
    table.add_column("Saved At")

    for e in entries:
        status_style = "green" if e.status == "passed" else "red"
        table.add_row(
            e.tag,
            e.scenario_id,
            f"[{status_style}]{e.status}[/{status_style}]",
            f"${e.estimated_cost:.6f}",
            f"{e.total_duration_ms:.0f}ms",
            f"{e.checks_passed}✓/{e.checks_failed}✗",
            e.timestamp[:19],
        )

    console.print(table)


@baseline.command("compare")
@click.argument("trace_path", type=click.Path(exists=True))
@click.option("--tag", "-t", required=True, help="Baseline tag to compare against")
@click.option("--cost-threshold", type=float, default=15.0, help="Cost drift threshold (percent)")
@click.option("--latency-threshold", type=float, default=200.0, help="Latency drift threshold (ms)")
@click.option("--dir", "baselines_dir", default=".scenetrace", help="Baselines directory")
def baseline_compare(trace_path: str, tag: str, cost_threshold: float, latency_threshold: float, baselines_dir: str) -> None:
    """Compare a trace against a saved baseline."""
    from scen_trace.baselines import BaselineRegistry

    registry = BaselineRegistry(baselines_dir=Path(baselines_dir))
    try:
        result = registry.compare(
            Path(trace_path), tag,
            cost_threshold_pct=cost_threshold,
            latency_threshold_ms=latency_threshold,
        )
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    finally:
        registry.close()

    # Drift summary
    severity_icons = {"ok": "[green]✅[/green]", "warning": "[yellow]⚠️[/yellow]", "critical": "[red]❌[/red]"}
    overall_colors = {"stable": "green", "warning": "yellow", "regression": "red"}
    overall_color = overall_colors.get(result.overall, "white")

    drift_lines = []
    for d in result.drifts:
        icon = severity_icons.get(d.severity, "")
        drift_lines.append(f"  {icon} {d.message}")

    if result.check_flips:
        for flip in result.check_flips:
            direction_icon = "[red]❌[/red]" if flip["direction"] == "regression" else "[green]✅[/green]"
            drift_lines.append(f"  {direction_icon} Check '{flip['check_id']}': {flip['baseline']} → {flip['current']}")

    console.print(Panel(
        f"[bold]Comparison against baseline:[/bold] [{overall_color}]{tag}[/{overall_color}]\n"
        f"[bold]Overall:[/bold] [{overall_color}]{result.overall.upper()}[/{overall_color}]\n\n"
        + "\n".join(drift_lines),
        title="Baseline Comparison",
        border_style=overall_color,
    ))

    # Detailed table
    table = Table(title="Drift Details")
    table.add_column("Metric")
    table.add_column("Baseline")
    table.add_column("Current")
    table.add_column("Delta")
    table.add_column("Status")

    for d in result.drifts:
        status_style = {"ok": "green", "warning": "yellow", "critical": "red"}.get(d.severity, "white")
        table.add_row(
            d.field,
            str(d.baseline_value),
            str(d.current_value),
            str(d.delta),
            f"[{status_style}]{d.severity.upper()}[/{status_style}]",
        )

    console.print(table)

    if result.overall == "regression":
        sys.exit(1)


@baseline.command("rm")
@click.argument("tag")
@click.option("--dir", "baselines_dir", default=".scenetrace", help="Baselines directory")
def baseline_rm(tag: str, baselines_dir: str) -> None:
    """Remove a saved baseline."""
    from scen_trace.baselines import BaselineRegistry

    registry = BaselineRegistry(baselines_dir=Path(baselines_dir))
    removed = registry.remove(tag)
    registry.close()

    if removed:
        console.print(f"[green]Baseline '{tag}' removed.[/green]")
    else:
        console.print(f"[yellow]No baseline found with tag '{tag}'.[/yellow]")


@cli.group()
def plugin() -> None:
    """Manage ScenTrace plugins."""


@plugin.command("list")
def plugin_list() -> None:
    """List discovered provider and check plugins."""
    from scen_trace.plugins import CHECK_GROUP, PROVIDER_GROUP, discover_plugins, load_plugin

    providers = discover_plugins(PROVIDER_GROUP)
    checks = discover_plugins(CHECK_GROUP)

    if not providers and not checks:
        console.print(Panel(
            "[yellow]No external plugins discovered.[/yellow]\n\n"
            "[dim]Built-in providers:[/dim] mock, openai\n"
            "[dim]Built-in checks:[/dim] contains, forbidden, regex, json_valid, python, semantic\n\n"
            "To create a plugin, register entry points under:\n"
            f"  [cyan]{PROVIDER_GROUP}[/cyan] (for providers)\n"
            f"  [cyan]{CHECK_GROUP}[/cyan] (for checks)\n\n"
            "Install plugins with: [cyan]pip install scenetrace-<plugin>[/cyan]",
            title="ScenTrace Plugins",
            border_style="blue",
        ))
        return

    table = Table(title="Discovered Plugins")
    table.add_column("Name", style="bold cyan")
    table.add_column("Type")
    table.add_column("Package")
    table.add_column("Version")
    table.add_column("Status")

    for p in providers:
        loaded = load_plugin(p)
        status = "[green]OK[/green]" if loaded.loaded else f"[red]Error: {loaded.error}[/red]"
        table.add_row(p.name, "provider", p.distribution, p.version, status)

    for c in checks:
        loaded = load_plugin(c)
        status = "[green]OK[/green]" if loaded.loaded else f"[red]Error: {loaded.error}[/red]"
        table.add_row(c.name, "check", c.distribution, c.version, status)

    console.print(table)

    console.print(f"\n[dim]Built-in providers: mock, openai[/dim]")
    console.print(f"[dim]Built-in checks: contains, forbidden, regex, json_valid, python, semantic[/dim]")


@cli.group()
def analytics() -> None:
    """Track and analyze historical run metrics."""


@analytics.command("init")
@click.option("--dir", "analytics_dir", default=".scenetrace", help="Analytics directory")
def analytics_init(analytics_dir: str) -> None:
    """Initialize the analytics database."""
    from scen_trace.analytics import AnalyticsDB

    db = AnalyticsDB(analytics_dir=Path(analytics_dir))
    db.init()
    console.print(f"[green]Analytics database initialized at {analytics_dir}/analytics.db[/green]")
    db.close()


@analytics.command("track")
@click.argument("trace_path", type=click.Path(exists=True))
@click.option("--dir", "analytics_dir", default=".scenetrace", help="Analytics directory")
def analytics_track(trace_path: str, analytics_dir: str) -> None:
    """Ingest a trace file into the analytics database."""
    from scen_trace.analytics import AnalyticsDB

    db = AnalyticsDB(analytics_dir=Path(analytics_dir))
    try:
        db.init()
        run_id = db.ingest_run(Path(trace_path))
        console.print(f"[green]Trace ingested as run #{run_id}[/green]")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    finally:
        db.close()


@analytics.command("report")
@click.argument("scenario_id")
@click.option("--dir", "analytics_dir", default=".scenetrace", help="Analytics directory")
@click.option("--limit", type=int, default=30, help="Number of recent runs to analyze")
def analytics_report(scenario_id: str, analytics_dir: str, limit: int) -> None:
    """Show analytics report for a scenario."""
    from scen_trace.analytics import AnalyticsDB

    db = AnalyticsDB(analytics_dir=Path(analytics_dir))
    try:
        trends = db.get_trends(scenario_id, limit=limit)
        if trends.total_runs == 0:
            console.print(f"[yellow]No runs found for scenario '{scenario_id}'.[/yellow]")
            db.close()
            return

        efficiency = db.compute_efficiency(scenario_id)

        # Efficiency score panel
        score_color = "green" if efficiency.total >= 70 else "yellow" if efficiency.total >= 40 else "red"
        score_bar = _score_bar(efficiency.total)
        console.print(Panel(
            f"[bold]Efficiency Score:[/bold] [{score_color}]{efficiency.total}/100[/{score_color}] {score_bar}\n\n"
            f"  Checks (40%):  {_score_bar(efficiency.check_score)} {efficiency.check_score}/100\n"
            f"  Cost (30%):    {_score_bar(efficiency.cost_score)} {efficiency.cost_score}/100\n"
            f"  Latency (20%): {_score_bar(efficiency.latency_score)} {efficiency.latency_score}/100\n"
            f"  Tokens (10%):  {_score_bar(efficiency.token_score)} {efficiency.token_score}/100",
            title=f"ScenTrace Analytics: {scenario_id}",
            border_style=score_color,
        ))

        # Trends table
        trends_table = Table(title="Run Trends")
        trends_table.add_column("Metric", style="bold")
        trends_table.add_column("Value")
        trends_table.add_row("Total Runs", str(trends.total_runs))
        trends_table.add_row("Avg Cost", f"${trends.avg_cost:.6f}")
        trends_table.add_row("Avg Latency", f"{trends.avg_latency_ms:.0f}ms")
        trends_table.add_row("Avg Tokens", str(trends.avg_tokens))
        trends_table.add_row("Pass Rate", f"{trends.pass_rate_pct:.1f}%")
        console.print(trends_table)

        # Agent breakdown
        if trends.agent_breakdown:
            agent_table = Table(title="Agent Cost Breakdown (Latest Run)")
            agent_table.add_column("Agent", style="cyan")
            agent_table.add_column("Turns")
            agent_table.add_column("Tokens")
            agent_table.add_column("Avg Latency")
            agent_table.add_column("Cost Share")
            for a in trends.agent_breakdown:
                agent_table.add_row(
                    a.agent_name,
                    str(a.turn_count),
                    str(a.total_tokens),
                    f"{a.avg_latency_ms:.0f}ms",
                    f"{a.cost_share_pct:.1f}%",
                )
            console.print(agent_table)

        # Recent runs
        if trends.recent_runs:
            runs_table = Table(title=f"Recent Runs (last {min(len(trends.recent_runs), 10)})")
            runs_table.add_column("#", style="dim")
            runs_table.add_column("Status")
            runs_table.add_column("Cost")
            runs_table.add_column("Latency")
            runs_table.add_column("Tokens")
            runs_table.add_column("Checks")
            runs_table.add_column("Time")

            for r in trends.recent_runs[:10]:
                status_style = "green" if r.status == "passed" else "red"
                runs_table.add_row(
                    str(r.id),
                    f"[{status_style}]{r.status}[/{status_style}]",
                    f"${r.total_cost:.6f}",
                    f"{r.total_latency_ms:.0f}ms",
                    str(r.total_tokens),
                    f"{r.checks_passed}✓/{r.checks_failed}✗",
                    r.timestamp[:19],
                )
            console.print(runs_table)

        # Cost trend alerts
        if trends.total_runs >= 3:
            costs = [r.total_cost for r in trends.recent_runs]
            avg_cost = sum(costs) / len(costs)
            latest_cost = costs[0] if costs else 0
            if avg_cost > 0 and latest_cost > avg_cost * 1.2:
                pct = (latest_cost - avg_cost) / avg_cost * 100
                console.print(f"\n[yellow]⚠️  Cost alert: Latest run exceeds average by {pct:.0f}%[/yellow]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    finally:
        db.close()


def _score_bar(score: int) -> str:
    filled = score // 10
    empty = 10 - filled
    return f"[green]{'█' * filled}[/green][dim]{'░' * empty}[/dim]"


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to (default: localhost only)")
@click.option("--port", "-p", default=8000, type=int, help="Port to bind to")
@click.option("--analytics-dir", default=".scenetrace", help="Analytics DB directory")
@click.option("--no-open", is_flag=True, help="Don't open browser automatically")
def serve(host: str, port: int, analytics_dir: str, no_open: bool) -> None:
    """Start a local web dashboard to visualize analytics and traces."""
    try:
        import uvicorn  # noqa: F401
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        console.print(Panel(
            "[yellow]Web dashboard requires extra dependencies.[/yellow]\n\n"
            'Install with:\n  [cyan]pip install "scen-trace[web]"[/cyan]',
            title="Missing Web Dependencies",
            border_style="yellow",
        ))
        sys.exit(1)

    from scen_trace.server import create_app

    db_path = Path(analytics_dir) / "analytics.db"
    if not db_path.exists():
        console.print("[yellow]No analytics database found. Initializing...[/yellow]")
        from scen_trace.analytics import AnalyticsDB
        db = AnalyticsDB(analytics_dir=Path(analytics_dir))
        db.init()
        db.close()

    app = create_app(analytics_dir=Path(analytics_dir))

    console.print(Panel(
        f"[bold green]ScenTrace Dashboard[/bold green]\n\n"
        f"  URL: [cyan]http://{host}:{port}[/cyan]\n"
        f"  Analytics: {analytics_dir}/analytics.db\n\n"
        "  Press [bold]Ctrl+C[/bold] to stop",
        title="Local Dashboard",
        border_style="blue",
    ))

    if not no_open:
        import threading
        def open_later() -> None:
            import time
            time.sleep(1)
            webbrowser.open(f"http://{host}:{port}")
        threading.Thread(target=open_later, daemon=True).start()

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]")


@cli.command()
def sync() -> None:
    """Sync traces and baselines across your team (coming in V2)."""
    console.print(Panel(
        "[bold cyan]Team trace syncing & baseline management coming in ScenTrace V2.[/bold cyan]\n\n"
        "This will enable:\n"
        "  • Shared baseline traces across CI runners and developers\n"
        "  • Regression comparison across PRs\n"
        "  • Team dashboards for trace analytics\n\n"
        "[dim]Follow the project for updates.[/dim]",
        title="ScenTrace Sync",
        border_style="cyan",
    ))
