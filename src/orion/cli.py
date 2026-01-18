"""Command-line interface for Orion screening platform.

This module provides Click-based commands for running screenings,
viewing history, and checking system status.
"""

import asyncio
import json
from datetime import datetime
from enum import Enum
from pathlib import Path

import click
from xdg import BaseDirectory

from orion.config import load_config
from orion.core.screener import StockScreener
from orion.data.providers.alpha_vantage import AlphaVantageProvider
from orion.data.providers.yahoo_finance import YahooFinanceProvider
from orion.notifications.models import NotificationConfig
from orion.notifications.service import NotificationService
from orion.storage import Database, ResultRepository
from orion.strategies.parser import StrategyParser
from orion.utils.logging import get_logger, setup_logging

logger = get_logger(__name__, component="CLI")


class OutputFormat(str, Enum):
    """Output format options for CLI commands."""

    JSON = "json"
    TABLE = "table"
    PRETTY = "pretty"


def get_config_dir() -> Path:
    """Get the Orion configuration directory.

    Returns:
        Path to the config directory (default: ~/.config/orion/)
    """
    return Path(BaseDirectory.xdg_config_home) / "orion"


def get_config_file() -> Path:
    """Get the path to the Orion config file.

    Returns:
        Path to config.yaml or a default.
    """
    return get_config_dir() / "config.yaml"


def get_db_path() -> Path:
    """Get the path to the Orion database file.

    Returns:
        Path to screenings.db in the config directory.
    """
    db_dir = get_config_dir() / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "screenings.db"


def get_default_strategy_path() -> Path:
    """Get the path to the default strategy file.

    Returns:
        Path to strategies/ofi.yaml relative to project root.
    """
    # Try to find the strategies directory relative to this file
    here = Path(__file__).parent
    project_root = here.parent.parent
    strategy_path = project_root / "strategies" / "ofi.yaml"

    if strategy_path.exists():
        return strategy_path

    # Fallback to a system-wide location
    return get_config_dir() / "ofi.yaml"


def load_notification_config() -> NotificationConfig:
    """Load notification configuration from environment.

    Returns:
        NotificationConfig instance with settings from environment.
    """
    return NotificationConfig.from_env()


def format_timestamp(ts: str) -> str:
    """Format an ISO timestamp for display.

    Args:
        ts: ISO format timestamp string.

    Returns:
        Formatted timestamp string.
    """
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Set logging level",
)
@click.option(
    "--log-format",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Set log output format",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to config file",
)
@click.pass_context
def cli(ctx: click.Context, log_level: str, log_format: str, config: str | None) -> None:
    """Orion - Trading signals platform for Option for Income opportunities.

    This CLI tool helps you run stock screenings, view historical results,
    and check system status.
    """
    # Setup logging
    setup_logging(level=log_level, format_type=log_format)

    # Store context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level
    ctx.obj["log_format"] = log_format
    ctx.obj["config_file"] = config

    # Load configuration
    try:
        if config:
            app_config = load_config(env_file=config)
        else:
            app_config = load_config()
        ctx.obj["config"] = app_config
    except Exception as e:
        logger.warning("config_load_failed", error=str(e))
        ctx.obj["config"] = None


@cli.command()
@click.option(
    "--strategy",
    type=click.Path(exists=True),
    help="Path to strategy YAML file (default: strategies/ofi.yaml)",
)
@click.option(
    "--symbols",
    help="Comma-separated list of symbols to screen",
)
@click.option(
    "--notify/--no-notify",
    default=False,
    help="Send notifications for matches",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show matches without saving to database",
)
@click.option(
    "--output",
    type=click.Choice(["json", "table", "pretty"]),
    default="pretty",
    help="Output format",
)
@click.option(
    "--provider",
    type=click.Choice(["yahoo", "alpha_vantage"]),
    default="yahoo",
    help="Data provider to use",
)
@click.pass_context
def run(
    ctx: click.Context,
    strategy: str | None,
    symbols: str | None,
    notify: bool,
    dry_run: bool,
    output: str,
    provider: str,
) -> None:
    """Execute a stock screening run.

    Runs the screening pipeline for the specified symbols (or default list)
    using the given strategy. Matching results can be saved to the database
    and sent via email notification.
    """
    asyncio.run(_run_screening(strategy, symbols, notify, dry_run, output, provider))


async def _run_screening(
    strategy: str | None,
    symbols: str | None,
    notify: bool,
    dry_run: bool,
    output: str,
    provider: str,
) -> None:
    """Async implementation of the run command."""
    # Determine strategy path
    if strategy:
        strategy_path = Path(strategy)
    else:
        strategy_path = get_default_strategy_path()

    if not strategy_path.exists():
        click.echo(f"Error: Strategy file not found: {strategy_path}", err=True)
        click.echo(
            "\nHint: Create a strategy file or use --strategy to specify a path.",
            err=True,
        )
        raise click.Abort()

    # Load strategy
    parser = StrategyParser()
    try:
        trading_strategy = parser.parse_file(strategy_path)
        logger.info("strategy_loaded", name=trading_strategy.name)
    except Exception as e:
        click.echo(f"Error loading strategy: {e}", err=True)
        raise click.Abort() from e

    # Determine symbols to screen
    if symbols:
        symbol_list = [s.strip().upper() for s in symbols.split(",")]
    else:
        # Default list of large-cap stocks for OFI strategy
        symbol_list = [
            "AAPL",
            "MSFT",
            "GOOGL",
            "AMZN",
            "META",
            "NVDA",
            "TSLA",
            "JPM",
            "V",
            "WMT",
        ]

    click.echo(f"Screening {len(symbol_list)} symbols with strategy '{trading_strategy.name}'...")
    click.echo(f"Symbols: {', '.join(symbol_list)}")
    click.echo()

    # Initialize data provider
    config = load_config()
    if provider == "yahoo":
        data_provider: YahooFinanceProvider | AlphaVantageProvider = YahooFinanceProvider()
    else:
        if not config.data_provider.api_key:
            click.echo(
                "Error: ALPHA_VANTAGE_API_KEY not set. Set environment variable or use --provider yahoo",
                err=True,
            )
            raise click.Abort()
        data_provider = AlphaVantageProvider(config.data_provider)

    # Initialize screener
    screener = StockScreener(
        provider=data_provider,  # type: ignore[arg-type]
        strategy=trading_strategy,
        max_concurrent=config.screening.max_concurrent_requests,
    )

    # Run screening
    click.echo("Running screening...")
    matches, stats = await screener.screen_and_filter(symbol_list)

    # Display results
    click.echo()
    click.echo(f"Screening complete in {stats.duration_seconds:.1f} seconds")
    click.echo(f"Total symbols: {stats.total_symbols}")
    click.echo(f"Successful: {stats.successful}")
    click.echo(f"Failed: {stats.failed}")
    click.echo(f"Matches: {stats.matches}")
    click.echo()

    if not matches:
        click.echo("No matches found.")
        return

    # Display matches
    if output == "json":
        output_json = []
        for result in matches:
            output_json.append(
                {
                    "symbol": result.symbol,
                    "signal_strength": result.signal_strength,
                    "conditions_met": result.conditions_met,
                    "quote": {
                        "price": str(result.quote.price) if result.quote else None,
                        "change": str(result.quote.change) if result.quote else None,
                        "change_percent": result.quote.change_percent if result.quote else None,
                    }
                    if result.quote
                    else None,
                    "option": (
                        {
                            "strike": str(result.option_recommendation.strike),
                            "expiration": result.option_recommendation.expiration.isoformat(),
                            "premium_yield": result.option_recommendation.premium_yield,
                            "mid_price": str(result.option_recommendation.mid_price),
                        }
                        if result.option_recommendation
                        else None
                    ),
                }
            )
        click.echo(json.dumps(output_json, indent=2))

    elif output in ("table", "pretty"):
        click.echo("Matching symbols:")
        click.echo("-" * 80)

        for result in matches:
            click.echo(f"\n{result.symbol}")
            if result.quote:
                click.echo(f"  Price: ${result.quote.price:.2f}", nl=False)
                if result.quote.change_percent:
                    direction = "+" if result.quote.change_percent > 0 else ""
                    click.echo(f"  ({direction}{result.quote.change_percent:.2f}%)")
                else:
                    click.echo()

            click.echo(f"  Signal Strength: {result.signal_strength:.1%}")
            click.echo(f"  Conditions Met: {', '.join(result.conditions_met)}")

            if result.option_recommendation:
                rec = result.option_recommendation
                click.echo()
                click.echo("  Option Recommendation:")
                click.echo(f"    Strike: ${rec.strike}")
                click.echo(f"    Expiration: {rec.expiration}")
                click.echo(f"    Premium Yield: {rec.premium_yield:.1%}")
                click.echo(f"    Mid Price: ${rec.mid_price:.2f}")
                click.echo(f"    Volume: {rec.volume}")
                click.echo(f"    Open Interest: {rec.open_interest}")

    # Save to database (unless dry run)
    if not dry_run:
        db_path = get_db_path()
        db = Database(db_path)
        await db.connect()

        try:
            repo = ResultRepository(db)
            run_id = await repo.save_run(stats, trading_strategy.name)
            await repo.save_results(matches, run_id)
            logger.info("results_saved", run_id=run_id, matches=len(matches))
            click.echo(f"\nResults saved to database (run_id: {run_id})")
        finally:
            await db.close()

    # Send notifications
    if notify and matches:
        notification_config = load_notification_config()
        if notification_config.is_valid():
            notification_service = NotificationService(notification_config)

            if len(matches) == 1:
                sent_count = await notification_service.send_alert(matches[0])
                sent_ok = sent_count > 0
            else:
                batch_count = await notification_service.send_batch_alerts(matches)
                sent_ok = batch_count > 0

            if sent_ok:
                click.echo(
                    f"\nNotifications sent to {len(notification_config.to_addresses)} recipients"
                )
            else:
                click.echo("\nFailed to send notifications")
        else:
            click.echo("\nNotifications not configured.")


@cli.command()
@click.option(
    "--symbol",
    help="Filter by symbol",
)
@click.option(
    "--days",
    type=int,
    default=30,
    help="Days to look back (default: 30)",
)
@click.option(
    "--count",
    type=int,
    default=50,
    help="Maximum results to show (default: 50)",
)
@click.option(
    "--output",
    type=click.Choice(["json", "table", "pretty"]),
    default="table",
    help="Output format",
)
@click.option(
    "--matches-only",
    is_flag=True,
    help="Show only matching results",
)
@click.pass_context
def history(
    ctx: click.Context,
    symbol: str | None,
    days: int,
    count: int,
    output: str,
    matches_only: bool,
) -> None:
    """View screening history.

    Shows historical screening results from the database.
    Filter by symbol, date range, or show only matches.
    """
    asyncio.run(_history(symbol, days, count, output, matches_only))


async def _history(
    symbol: str | None,
    days: int,
    count: int,
    output: str,
    matches_only: bool,
) -> None:
    """Async implementation of the history command."""
    db_path = get_db_path()

    if not db_path.exists():
        click.echo("No database found. Run a screening first with `orion run`")
        raise click.Abort()

    db = Database(db_path)
    await db.connect()

    try:
        repo = ResultRepository(db)

        if symbol:
            # Get results for specific symbol
            results = await repo.get_results_by_symbol(symbol.upper(), days)
        elif matches_only:
            # Get recent matches
            results = await repo.get_recent_matches(days, count)
        else:
            # Get recent runs
            runs = await repo.get_recent_runs(count)
            results = [{"runs": runs}]

        if not results:
            click.echo("No results found.")
            return

        if output == "json":
            click.echo(json.dumps(results, indent=2, default=str))

        elif output == "table":
            if symbol and not matches_only:
                # Show symbol history as table
                click.echo(f"Screening history for {symbol} (last {days} days):")
                click.echo("-" * 80)
                click.echo(f"{'Timestamp':<20} {'Match':<6} {'Signal':<8} {'Conditions Met'}")
                click.echo("-" * 80)

                for r in results:
                    timestamp = format_timestamp(r["timestamp"])[:19]
                    match_str = "Yes" if r["matches"] else "No"
                    signal = f"{r['signal_strength']:.0%}"
                    conditions = ", ".join(r["conditions_met"]) if r["conditions_met"] else "-"
                    click.echo(f"{timestamp:<20} {match_str:<6} {signal:<8} {conditions}")

            elif matches_only:
                # Show matches as table
                click.echo(f"Recent matches (last {days} days):")
                click.echo("-" * 100)
                click.echo(
                    f"{'Timestamp':<20} {'Symbol':<8} {'Signal':<8} {'Strike':<10} {'Yield':<8} {'Strategy'}"
                )
                click.echo("-" * 100)

                for r in results:
                    timestamp = format_timestamp(r["timestamp"])[:19]
                    sym = r["symbol"]
                    signal = f"{r['signal_strength']:.0%}"
                    strike = r.get("option_strike", "N/A")
                    yield_val = (
                        f"{r.get('premium_yield', 0):.0%}" if r.get("premium_yield") else "-"
                    )
                    strategy = r.get("strategy_name", "N/A")
                    click.echo(
                        f"{timestamp:<20} {sym:<8} {signal:<8} {strike:<10} {yield_val:<8} {strategy}"
                    )

            else:
                # Show runs summary
                for item in results:
                    if "runs" in item:
                        runs = item["runs"]
                        click.echo("Recent screening runs:")
                        click.echo("-" * 80)
                        click.echo(
                            f"{'Timestamp':<20} {'Strategy':<20} {'Symbols':<8} {'Matches':<8} {'Duration':<10}"
                        )
                        click.echo("-" * 80)

                        for r in runs:
                            timestamp = format_timestamp(r["timestamp"])[:19]
                            strategy = r["strategy_name"]
                            symbols = r["symbols_count"]
                            matches = r["matches_count"]
                            duration = f"{r['duration_seconds']:.1f}s"
                            click.echo(
                                f"{timestamp:<20} {strategy:<20} {symbols:<8} {matches:<8} {duration:<10}"
                            )

        elif output == "pretty":
            if symbol:
                click.echo(f"Screening history for {symbol} (last {days} days):")
                click.echo()

                for r in results:
                    click.echo(f"{'✓' if r['matches'] else '✗'} {format_timestamp(r['timestamp'])}")
                    if r["matches"]:
                        click.echo(f"  Signal: {r['signal_strength']:.1%}")
                        click.echo(f"  Conditions: {', '.join(r['conditions_met'])}")
                        if r.get("option_recommendation"):
                            opt = r["option_recommendation"]
                            click.echo(f"  Option: {opt['strike']} exp {opt['expiration']}")
                    click.echo()

            elif matches_only:
                click.echo(f"Recent matches (last {days} days):")
                click.echo()

                for r in results:
                    click.echo(f"🎯 {r['symbol']} - {format_timestamp(r['timestamp'])}")
                    click.echo(f"   Signal: {r['signal_strength']:.1%}")
                    if r.get("option_strike"):
                        click.echo(
                            f"   Option: {r['option_strike']} (Yield: {r.get('premium_yield', 0):.1%})"
                        )
                    click.echo()

    finally:
        await db.close()


@cli.command()
@click.option(
    "--output",
    type=click.Choice(["json", "pretty"]),
    default="pretty",
    help="Output format",
)
@click.pass_context
def status(ctx: click.Context, output: str) -> None:
    """Show system status.

    Displays information about the last screening run, recent matches,
    and database statistics.
    """
    asyncio.run(_status(output))


async def _status(output: str) -> None:
    """Async implementation of the status command."""
    db_path = get_db_path()

    if not db_path.exists():
        click.echo("Database not found. Run a screening first.")
        click.echo()
        click.echo(f"Database path: {db_path}")
        click.echo(f"Config directory: {get_config_dir()}")
        click.echo(f"Default strategy: {get_default_strategy_path()}")
        return

    db = Database(db_path)
    await db.connect()

    try:
        repo = ResultRepository(db)
        stats = await repo.get_statistics()

        if output == "json":
            click.echo(json.dumps(stats, indent=2, default=str))

        else:
            click.echo("Orion System Status")
            click.echo("=" * 40)
            click.echo()

            # Overall stats
            click.echo(f"Total screening runs: {stats.get('total_runs', 0)}")
            click.echo(f"Total results: {stats.get('total_results', 0)}")
            click.echo(f"Recent matches (30d): {stats.get('recent_matches_30d', 0)}")
            click.echo(f"Average matches per run: {stats.get('avg_matches_per_run', 0):.1f}")
            click.echo()

            # Last run
            last_run = stats.get("last_run")
            if last_run and last_run.get("timestamp"):
                click.echo("Last screening run:")
                click.echo(f"  Time: {format_timestamp(last_run['timestamp'])}")
                click.echo(f"  Strategy: {last_run.get('strategy', 'N/A')}")
                click.echo(f"  Symbols: {last_run.get('symbols', 0)}")
                click.echo(f"  Matches: {last_run.get('matches', 0)}")
            else:
                click.echo("No screening runs recorded yet.")
            click.echo()

            # Configuration
            click.echo("Configuration:")
            click.echo(f"  Database: {db_path}")
            click.echo(f"  Config dir: {get_config_dir()}")
            click.echo(f"  Strategy: {get_default_strategy_path()}")

    finally:
        await db.close()


# Main entry point
def main() -> None:
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
