"""Repository for managing screening results in the database.

This module provides a higher-level interface for working with screening
results, handling conversion between domain models and database records.
"""

import json

import aiosqlite

from orion.core.screener import ScreeningResult, ScreeningStats
from orion.data.models import Quote, TechnicalIndicators
from orion.storage.database import Database
from orion.strategies.models import OptionRecommendation
from orion.utils.logging import get_logger

logger = get_logger(__name__, component="ResultRepository")


class ResultRepository:
    """Repository for screening run and result persistence.

    Provides async methods for saving and querying screening data,
    handling conversion between domain models and database records.

    Example:
        >>> db = Database("~/orion/screenings.db")
        >>> await db.initialize()
        >>> repo = ResultRepository(db)
        >>> run_id = await repo.save_run(stats, "ofi")
        >>> await repo.save_result(result, run_id)
        >>> history = await repo.get_results_by_symbol("AAPL", days=30)
    """

    def __init__(self, database: Database) -> None:
        """Initialize the repository.

        Args:
            database: Database instance to use for persistence.
        """
        self.db = database
        self._logger = logger

    async def save_run(
        self,
        stats: ScreeningStats,
        strategy_name: str,
    ) -> int:
        """Save a screening run to the database.

        Args:
            stats: Screening statistics from the run.
            strategy_name: Name of the strategy used.

        Returns:
            The ID of the inserted run.
        """
        self._logger.info(
            "saving_run",
            strategy=strategy_name,
            symbols=stats.total_symbols,
            matches=stats.matches,
        )

        run_id = await self.db.insert_run(
            strategy_name=strategy_name,
            symbols_count=stats.total_symbols,
            matches_count=stats.matches,
            duration_seconds=stats.duration_seconds,
            timestamp=stats.start_time,
        )

        return run_id

    async def save_result(self, result: ScreeningResult, run_id: int) -> int:
        """Save a screening result to the database.

        Args:
            result: ScreeningResult to persist.
            run_id: ID of the associated screening run.

        Returns:
            The ID of the inserted result.
        """
        self._logger.info(
            "saving_result", symbol=result.symbol, run_id=run_id, matches=result.matches
        )

        # Convert domain models to dicts for JSON serialization
        quote_data = self._quote_to_dict(result.quote) if result.quote else None
        indicators_data = self._indicators_to_dict(result.indicators) if result.indicators else None
        option_rec_data = (
            self._option_recommendation_to_dict(result.option_recommendation)
            if result.option_recommendation
            else None
        )

        result_id = await self.db.insert_result(
            run_id=run_id,
            symbol=result.symbol,
            matches=result.matches,
            signal_strength=result.signal_strength,
            conditions_met=result.conditions_met,
            conditions_missed=result.conditions_missed,
            timestamp=result.timestamp,
            quote_data=quote_data,
            indicators_data=indicators_data,
            option_recommendation=option_rec_data,
            error_message=result.error,
        )

        return result_id

    async def save_results(self, results: list[ScreeningResult], run_id: int) -> list[int]:
        """Save multiple screening results to the database.

        Args:
            results: List of ScreeningResult objects to persist.
            run_id: ID of the associated screening run.

        Returns:
            List of inserted result IDs.
        """
        self._logger.info("saving_results", count=len(results), run_id=run_id)

        result_ids = []
        for result in results:
            result_id = await self.save_result(result, run_id)
            result_ids.append(result_id)

        self._logger.info("results_saved", count=len(result_ids), run_id=run_id)
        return result_ids

    async def get_results_by_symbol(self, symbol: str, days: int = 30) -> list[dict]:
        """Get screening history for a specific symbol.

        Args:
            symbol: Stock symbol to query.
            days: Number of days to look back.

        Returns:
            List of result dictionaries with screening data.
        """
        self._logger.info("getting_results_by_symbol", symbol=symbol, days=days)

        rows = await self.db.get_results_by_symbol(symbol, days)

        results = []
        for row in rows:
            results.append(self._row_to_result_dict(row))

        return results

    async def get_recent_matches(self, days: int = 30, limit: int = 100) -> list[dict]:
        """Get recent matching screening results.

        Args:
            days: Number of days to look back.
            limit: Maximum number of results to return.

        Returns:
            List of result dictionaries with matching screenings.
        """
        self._logger.info("getting_recent_matches", days=days, limit=limit)

        rows = await self.db.get_recent_matches(days, limit)

        results = []
        for row in rows:
            results.append(self._row_to_match_dict(row))

        return results

    async def get_statistics(self) -> dict:
        """Get aggregate statistics from the database.

        Returns:
            Dictionary with screening statistics.
        """
        self._logger.info("getting_statistics")

        return await self.db.get_statistics()

    async def get_recent_runs(self, limit: int = 10) -> list[dict]:
        """Get recent screening runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of run dictionaries.
        """
        self._logger.info("getting_recent_runs", limit=limit)

        rows = await self.db.get_recent_runs(limit)

        runs = []
        for row in rows:
            runs.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "strategy_name": row["strategy_name"],
                    "symbols_count": row["symbols_count"],
                    "matches_count": row["matches_count"],
                    "duration_seconds": row["duration_seconds"],
                }
            )

        return runs

    @staticmethod
    def _quote_to_dict(quote: Quote) -> dict:
        """Convert a Quote model to a dictionary.

        Args:
            quote: Quote model to convert.

        Returns:
            Dictionary representation of the quote.
        """
        return {
            "symbol": quote.symbol,
            "price": str(quote.price),
            "volume": quote.volume,
            "timestamp": quote.timestamp.isoformat(),
            "open": str(quote.open),
            "high": str(quote.high),
            "low": str(quote.low),
            "close": str(quote.close),
            "previous_close": str(quote.previous_close) if quote.previous_close else None,
            "change": str(quote.change) if quote.change else None,
            "change_percent": quote.change_percent,
        }

    @staticmethod
    def _indicators_to_dict(indicators: TechnicalIndicators) -> dict:
        """Convert a TechnicalIndicators model to a dictionary.

        Args:
            indicators: TechnicalIndicators model to convert.

        Returns:
            Dictionary representation of the indicators.
        """
        return {
            "symbol": indicators.symbol,
            "timestamp": indicators.timestamp.isoformat(),
            "sma_20": indicators.sma_20,
            "sma_50": indicators.sma_50,
            "sma_60": indicators.sma_60,
            "sma_200": indicators.sma_200,
            "ema_12": indicators.ema_12,
            "ema_26": indicators.ema_26,
            "rsi_14": indicators.rsi_14,
            "macd": indicators.macd,
            "macd_signal": indicators.macd_signal,
            "macd_histogram": indicators.macd_histogram,
            "volume_avg_20": indicators.volume_avg_20,
            "volume_avg_50": indicators.volume_avg_50,
            "bollinger_upper": indicators.bollinger_upper,
            "bollinger_middle": indicators.bollinger_middle,
            "bollinger_lower": indicators.bollinger_lower,
            "atr_14": indicators.atr_14,
        }

    @staticmethod
    def _option_recommendation_to_dict(recommendation: OptionRecommendation) -> dict:
        """Convert an OptionRecommendation model to a dictionary.

        Args:
            recommendation: OptionRecommendation model to convert.

        Returns:
            Dictionary representation of the recommendation.
        """
        return {
            "symbol": recommendation.symbol,
            "underlying_symbol": recommendation.underlying_symbol,
            "strike": str(recommendation.strike),
            "expiration": recommendation.expiration.isoformat(),
            "option_type": recommendation.option_type,
            "bid": str(recommendation.bid),
            "ask": str(recommendation.ask),
            "mid_price": str(recommendation.mid_price),
            "premium_yield": recommendation.premium_yield,
            "volume": recommendation.volume,
            "open_interest": recommendation.open_interest,
            "implied_volatility": recommendation.implied_volatility,
            "delta": recommendation.delta,
            "reason": recommendation.reason,
        }

    @staticmethod
    def _row_to_result_dict(row: aiosqlite.Row) -> dict:
        """Convert a database row to a result dictionary.

        Args:
            row: Database row from screening_results table.

        Returns:
            Dictionary with result data.
        """
        # Convert Row to dict for safe access with .get()
        row_dict = dict(row)
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "symbol": row["symbol"],
            "timestamp": row["timestamp"],
            "matches": bool(row["matches"]),
            "signal_strength": row["signal_strength"],
            "conditions_met": json.loads(row["conditions_met"]) if row["conditions_met"] else [],
            "conditions_missed": (
                json.loads(row["conditions_missed"]) if row["conditions_missed"] else []
            ),
            "quote_data": json.loads(row["quote_data"]) if row["quote_data"] else None,
            "indicators_data": json.loads(row["indicators_data"])
            if row["indicators_data"]
            else None,
            "option_recommendation": (
                json.loads(row["option_recommendation"]) if row["option_recommendation"] else None
            ),
            "error_message": row["error_message"],
            "run_timestamp": row_dict.get("timestamp", ""),
            "strategy_name": row_dict.get("strategy_name", ""),
        }

    @staticmethod
    def _row_to_match_dict(row: aiosqlite.Row) -> dict:
        """Convert a database row to a match dictionary (simplified).

        Args:
            row: Database row from screening_results table.

        Returns:
            Dictionary with match data.
        """
        # Convert Row to dict for safe access with .get()
        row_dict = dict(row)
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "symbol": row["symbol"],
            "timestamp": row["timestamp"],
            "signal_strength": row["signal_strength"],
            "conditions_met": json.loads(row["conditions_met"]) if row["conditions_met"] else [],
            "quote_price": (json.loads(row["quote_data"])["price"] if row["quote_data"] else None),
            "option_strike": (
                json.loads(row["option_recommendation"])["strike"]
                if row["option_recommendation"]
                else None
            ),
            "premium_yield": (
                json.loads(row["option_recommendation"])["premium_yield"]
                if row["option_recommendation"]
                else None
            ),
            "strategy_name": row_dict.get("strategy_name", ""),
        }
