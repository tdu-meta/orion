"""Database schema and connection management for Orion.

This module provides async database operations using SQLite and aiosqlite,
with automatic schema creation and connection pooling.
"""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import aiosqlite

from orion.utils.logging import get_logger

logger = get_logger(__name__, component="Database")


class Database:
    """Async SQLite database manager for screening results.

    Handles database connection, schema creation, and provides async
    methods for CRUD operations on screening runs and results.

    Example:
        >>> db = Database("~/orion/screenings.db")
        >>> await db.initialize()
        >>> run_id = await db.insert_run("ofi", 100, 5, 30.5)
        >>> await db.insert_result(run_id, result)
        >>> await db.close()
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the database manager.

        Args:
            db_path: Path to the SQLite database file. Will be created
                     if it doesn't exist. Supports ~ expansion.
        """
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None
        self._logger = logger

    async def connect(self) -> aiosqlite.Connection:
        """Get or create a database connection.

        Returns:
            Active aiosqlite connection with row factory enabled.
        """
        if self._conn is None:
            self._logger.info("database_connecting", path=str(self.db_path))
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._create_schema()
            self._logger.info("database_connected")
        return self._conn

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            self._logger.info("database_closed")

    async def _create_schema(self) -> None:
        """Create database tables if they don't exist."""
        conn = await self.connect()

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS screening_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                strategy_name TEXT NOT NULL,
                symbols_count INTEGER NOT NULL,
                matches_count INTEGER NOT NULL,
                duration_seconds REAL NOT NULL
            )
        """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS screening_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                matches BOOLEAN NOT NULL,
                signal_strength REAL NOT NULL,
                conditions_met TEXT,
                conditions_missed TEXT,
                quote_data TEXT,
                indicators_data TEXT,
                option_recommendation TEXT,
                error_message TEXT,
                FOREIGN KEY (run_id) REFERENCES screening_runs(id) ON DELETE CASCADE
            )
        """
        )

        # Create indexes for common queries
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_results_run_id
            ON screening_results(run_id)
        """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_results_symbol
            ON screening_results(symbol)
        """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_results_timestamp
            ON screening_results(timestamp)
        """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_results_matches
            ON screening_results(matches)
        """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runs_timestamp
            ON screening_runs(timestamp)
        """
        )

        await conn.commit()
        self._logger.info("database_schema_created")

    async def insert_run(
        self,
        strategy_name: str,
        symbols_count: int,
        matches_count: int,
        duration_seconds: float,
        timestamp: datetime | None = None,
    ) -> int:
        """Insert a screening run record.

        Args:
            strategy_name: Name of the strategy used for screening.
            symbols_count: Number of symbols screened.
            matches_count: Number of symbols that matched.
            duration_seconds: Duration of the screening run in seconds.
            timestamp: Optional timestamp for the run (defaults to now).

        Returns:
            The ID of the inserted run.
        """
        conn = await self.connect()
        ts = timestamp or datetime.now()

        cursor = await conn.execute(
            """
            INSERT INTO screening_runs
            (timestamp, strategy_name, symbols_count, matches_count, duration_seconds)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ts.isoformat(), strategy_name, symbols_count, matches_count, duration_seconds),
        )

        await conn.commit()
        run_id = cursor.lastrowid or 0
        self._logger.info(
            "run_inserted",
            run_id=run_id,
            strategy=strategy_name,
            symbols=symbols_count,
            matches=matches_count,
        )
        return run_id

    async def insert_result(
        self,
        run_id: int,
        symbol: str,
        matches: bool,
        signal_strength: float,
        conditions_met: list[str],
        conditions_missed: list[str],
        timestamp: datetime,
        quote_data: dict | None = None,
        indicators_data: dict | None = None,
        option_recommendation: dict | None = None,
        error_message: str | None = None,
    ) -> int:
        """Insert a screening result record.

        Args:
            run_id: ID of the associated screening run.
            symbol: Stock symbol that was screened.
            matches: Whether the symbol matched the strategy.
            signal_strength: Signal strength (0.0 to 1.0).
            conditions_met: List of condition types that were met.
            conditions_missed: List of condition types that were missed.
            timestamp: When the screening was performed.
            quote_data: Optional quote data as dict.
            indicators_data: Optional technical indicators as dict.
            option_recommendation: Optional option recommendation as dict.
            error_message: Optional error message if screening failed.

        Returns:
            The ID of the inserted result.
        """
        conn = await self.connect()

        await conn.execute(
            """
            INSERT INTO screening_results
            (run_id, symbol, timestamp, matches, signal_strength, conditions_met,
             conditions_missed, quote_data, indicators_data, option_recommendation, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                symbol,
                timestamp.isoformat(),
                matches,
                signal_strength,
                json.dumps(conditions_met),
                json.dumps(conditions_missed),
                json.dumps(quote_data) if quote_data else None,
                json.dumps(indicators_data, default=self._json_serializer)
                if indicators_data
                else None,
                json.dumps(option_recommendation, default=self._json_serializer)
                if option_recommendation
                else None,
                error_message,
            ),
        )

        await conn.commit()

        # Get the last inserted row ID
        cursor = await conn.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        result_id: int = row[0] if row else 0

        self._logger.info("result_inserted", result_id=result_id, symbol=symbol, run_id=run_id)
        return result_id

    @staticmethod
    def _json_serializer(obj: object) -> str:
        """Custom JSON serializer for Decimal and datetime objects.

        Args:
            obj: Object to serialize.

        Returns:
            JSON-serializable string representation.

        Raises:
            TypeError: If the object type is not supported.
        """
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    async def get_results_by_symbol(self, symbol: str, days: int = 30) -> list[aiosqlite.Row]:
        """Get screening results for a specific symbol.

        Args:
            symbol: Stock symbol to query.
            days: Number of days to look back.

        Returns:
            List of screening result rows.
        """
        conn = await self.connect()

        cursor = await conn.execute(
            """
            SELECT r.*, sr.*
            FROM screening_results sr
            JOIN screening_runs r ON sr.run_id = r.id
            WHERE sr.symbol = ?
            AND datetime(sr.timestamp) >= datetime('now', '-' || ? || ' days')
            ORDER BY sr.timestamp DESC
            """,
            (symbol, days),
        )

        rows = list(await cursor.fetchall())
        self._logger.info("results_by_symbol_queried", symbol=symbol, count=len(rows), days=days)
        return rows

    async def get_recent_matches(self, days: int = 30, limit: int = 100) -> list[aiosqlite.Row]:
        """Get recent matching screening results.

        Args:
            days: Number of days to look back.
            limit: Maximum number of results to return.

        Returns:
            List of matching result rows.
        """
        conn = await self.connect()

        cursor = await conn.execute(
            """
            SELECT sr.*, r.strategy_name
            FROM screening_results sr
            JOIN screening_runs r ON sr.run_id = r.id
            WHERE sr.matches = 1
            AND datetime(sr.timestamp) >= datetime('now', '-' || ? || ' days')
            ORDER BY sr.timestamp DESC
            LIMIT ?
            """,
            (days, limit),
        )

        rows = list(await cursor.fetchall())
        self._logger.info("recent_matches_queried", count=len(rows), days=days, limit=limit)
        return rows

    async def get_statistics(self) -> dict:
        """Get aggregate statistics from the database.

        Returns:
            Dictionary with statistics including total runs, total results,
            recent match count, and success rate.
        """
        conn = await self.connect()

        # Total runs
        cursor = await conn.execute("SELECT COUNT(*) as count FROM screening_runs")
        total_runs_row = await cursor.fetchone()
        total_runs = total_runs_row["count"] if total_runs_row else 0

        # Total results
        cursor = await conn.execute("SELECT COUNT(*) as count FROM screening_results")
        total_results_row = await cursor.fetchone()
        total_results = total_results_row["count"] if total_results_row else 0

        # Matches in last 30 days
        cursor = await conn.execute(
            """
            SELECT COUNT(*) as count
            FROM screening_results
            WHERE matches = 1
            AND datetime(timestamp) >= datetime('now', '-30 days')
        """
        )
        recent_matches_row = await cursor.fetchone()
        recent_matches = recent_matches_row["count"] if recent_matches_row else 0

        # Most recent run
        cursor = await conn.execute(
            """
            SELECT timestamp, strategy_name, symbols_count, matches_count
            FROM screening_runs
            ORDER BY timestamp DESC
            LIMIT 1
        """
        )
        last_run = await cursor.fetchone()

        # Average matches per run
        cursor = await conn.execute(
            """
            SELECT AVG(matches_count) as avg_matches
            FROM screening_runs
        """
        )
        avg_matches_row = await cursor.fetchone()
        avg_matches = avg_matches_row["avg_matches"] if avg_matches_row else 0.0

        stats = {
            "total_runs": total_runs,
            "total_results": total_results,
            "recent_matches_30d": recent_matches,
            "last_run": {
                "timestamp": last_run["timestamp"] if last_run else None,
                "strategy": last_run["strategy_name"] if last_run else None,
                "symbols": last_run["symbols_count"] if last_run else 0,
                "matches": last_run["matches_count"] if last_run else 0,
            }
            if last_run
            else None,
            "avg_matches_per_run": round(avg_matches, 2),
        }

        self._logger.info("statistics_queried", **stats)
        return stats

    async def get_recent_runs(self, limit: int = 10) -> list[aiosqlite.Row]:
        """Get recent screening runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of screening run rows.
        """
        conn = await self.connect()

        cursor = await conn.execute(
            """
            SELECT * FROM screening_runs
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )

        rows = list(await cursor.fetchall())
        self._logger.info("recent_runs_queried", count=len(rows), limit=limit)
        return rows
