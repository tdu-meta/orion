"""Tests for storage module (database and repository)."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from orion.core.screener import ScreeningResult, ScreeningStats
from orion.data.models import Quote, TechnicalIndicators
from orion.storage import Database, ResultRepository
from orion.strategies.models import OptionRecommendation

# Use a consistent timestamp for tests (recent, within 30 days)
TEST_TIMESTAMP = datetime.now() - timedelta(days=1)


@pytest.fixture
def temp_db_path() -> Path:
    """Create a temporary database file path."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
async def db(temp_db_path: Path) -> Database:
    """Create a test database instance."""
    database = Database(temp_db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def repository(db: Database) -> ResultRepository:
    """Create a test repository instance."""
    return ResultRepository(db)


@pytest.fixture
def sample_stats() -> ScreeningStats:
    """Create sample screening statistics."""
    return ScreeningStats(
        total_symbols=10,
        successful=9,
        failed=1,
        matches=2,
        start_time=TEST_TIMESTAMP,
        end_time=TEST_TIMESTAMP + timedelta(seconds=90),
        duration_seconds=90.0,
    )


@pytest.fixture
def sample_quote() -> Quote:
    """Create a sample quote."""
    return Quote(
        symbol="AAPL",
        price=Decimal("185.50"),
        volume=1000000,
        timestamp=TEST_TIMESTAMP,
        open=Decimal("184.00"),
        high=Decimal("186.00"),
        low=Decimal("183.50"),
        close=Decimal("185.50"),
        previous_close=Decimal("183.00"),
        change=Decimal("2.50"),
        change_percent=1.37,
    )


@pytest.fixture
def sample_indicators() -> TechnicalIndicators:
    """Create sample technical indicators."""
    return TechnicalIndicators(
        symbol="AAPL",
        timestamp=TEST_TIMESTAMP,
        sma_20=185.0,
        sma_60=180.0,
        rsi_14=55.0,
        volume_avg_20=950000.0,
    )


@pytest.fixture
def sample_option_rec() -> OptionRecommendation:
    """Create a sample option recommendation."""
    return OptionRecommendation(
        symbol="AAPL250117P00180000",
        underlying_symbol="AAPL",
        strike=Decimal("180.00"),
        expiration=(TEST_TIMESTAMP + timedelta(days=2)).date(),
        option_type="put",
        bid=Decimal("1.50"),
        ask=Decimal("1.60"),
        mid_price=Decimal("1.55"),
        premium_yield=0.15,
        volume=500,
        open_interest=1000,
        implied_volatility=0.25,
        delta=-0.35,
        reason="ATM put with 15% annualized yield",
    )


@pytest.fixture
def sample_result(
    sample_quote: Quote,
    sample_indicators: TechnicalIndicators,
    sample_option_rec: OptionRecommendation,
) -> ScreeningResult:
    """Create a sample screening result."""
    return ScreeningResult(
        symbol="AAPL",
        timestamp=TEST_TIMESTAMP,
        matches=True,
        signal_strength=1.0,
        conditions_met=["trend", "oversold", "bounce"],
        conditions_missed=[],
        quote=sample_quote,
        indicators=sample_indicators,
        option_recommendation=sample_option_rec,
        evaluation_details={},
    )


class TestDatabase:
    """Tests for Database class."""

    @pytest.mark.asyncio
    async def test_database_initialization(self, temp_db_path: Path) -> None:
        """Test database creates file and schema on initialization."""
        db = Database(temp_db_path)
        await db.connect()

        # Check that file was created
        assert temp_db_path.exists()

        # Check tables exist by querying sqlite_master
        rows = await db._conn.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = [row[0] for row in rows]
        assert "screening_runs" in table_names
        assert "screening_results" in table_names

        await db.close()

    @pytest.mark.asyncio
    async def test_insert_run(self, db: Database) -> None:
        """Test inserting a screening run."""
        run_id = await db.insert_run(
            strategy_name="ofi",
            symbols_count=10,
            matches_count=2,
            duration_seconds=90.0,
            timestamp=TEST_TIMESTAMP,
        )

        assert run_id > 0

        # Verify the run was inserted
        cursor = await db._conn.execute("SELECT * FROM screening_runs WHERE id = ?", (run_id,))
        row = await cursor.fetchone()

        assert row["strategy_name"] == "ofi"
        assert row["symbols_count"] == 10
        assert row["matches_count"] == 2
        assert row["duration_seconds"] == 90.0

    @pytest.mark.asyncio
    async def test_insert_result(self, db: Database) -> None:
        """Test inserting a screening result."""
        run_id = await db.insert_run("ofi", 10, 2, 90.0)

        result_id = await db.insert_result(
            run_id=run_id,
            symbol="AAPL",
            matches=True,
            signal_strength=1.0,
            conditions_met=["trend", "oversold"],
            conditions_missed=[],
            timestamp=TEST_TIMESTAMP,
        )

        assert result_id > 0

        # Verify the result was inserted
        cursor = await db._conn.execute(
            "SELECT * FROM screening_results WHERE id = ?", (result_id,)
        )
        row = await cursor.fetchone()

        assert row["run_id"] == run_id
        assert row["symbol"] == "AAPL"
        assert row["matches"] == 1
        assert row["signal_strength"] == 1.0

    @pytest.mark.asyncio
    async def test_get_results_by_symbol(self, db: Database) -> None:
        """Test querying results by symbol."""
        # Insert test data
        run_id = await db.insert_run("ofi", 10, 2, 90.0)

        await db.insert_result(
            run_id=run_id,
            symbol="AAPL",
            matches=True,
            signal_strength=1.0,
            conditions_met=["trend"],
            conditions_missed=[],
            timestamp=TEST_TIMESTAMP,
        )

        # Query by symbol
        results = await db.get_results_by_symbol("AAPL", days=30)

        assert len(results) == 1
        assert results[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_get_recent_matches(self, db: Database) -> None:
        """Test querying recent matches."""
        # Insert test data
        run_id = await db.insert_run("ofi", 10, 2, 90.0)

        await db.insert_result(
            run_id=run_id,
            symbol="AAPL",
            matches=True,
            signal_strength=1.0,
            conditions_met=["trend"],
            conditions_missed=[],
            timestamp=TEST_TIMESTAMP,
        )

        await db.insert_result(
            run_id=run_id,
            symbol="MSFT",
            matches=False,
            signal_strength=0.5,
            conditions_met=[],
            conditions_missed=["trend"],
            timestamp=TEST_TIMESTAMP + timedelta(seconds=30),
        )

        # Query matches only
        matches = await db.get_recent_matches(days=30, limit=100)

        assert len(matches) == 1
        assert matches[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_get_statistics(self, db: Database) -> None:
        """Test getting aggregate statistics."""
        # Insert test data
        await db.insert_run("ofi", 10, 2, 90.0)
        await db.insert_run("ofi", 15, 3, 120.0)

        stats = await db.get_statistics()

        assert stats["total_runs"] == 2
        assert stats["avg_matches_per_run"] == 2.5

    @pytest.mark.asyncio
    async def test_json_serialization(self, db: Database) -> None:
        """Test JSON serialization of complex fields."""
        run_id = await db.insert_run("ofi", 10, 2, 90.0)

        # Insert result with quote data
        await db.insert_result(
            run_id=run_id,
            symbol="AAPL",
            matches=True,
            signal_strength=1.0,
            conditions_met=["trend", "oversold"],
            conditions_missed=[],
            timestamp=TEST_TIMESTAMP,
            quote_data={"price": "185.50", "volume": 1000000},
        )

        # Verify JSON was stored correctly
        cursor = await db._conn.execute(
            "SELECT quote_data FROM screening_results WHERE symbol = ?", ("AAPL",)
        )
        row = await cursor.fetchone()

        import json

        quote_data = json.loads(row["quote_data"])
        assert quote_data["price"] == "185.50"
        assert quote_data["volume"] == 1000000


class TestResultRepository:
    """Tests for ResultRepository class."""

    @pytest.mark.asyncio
    async def test_save_run(
        self, repository: ResultRepository, sample_stats: ScreeningStats
    ) -> None:
        """Test saving a screening run."""
        run_id = await repository.save_run(sample_stats, "ofi")

        assert run_id > 0

    @pytest.mark.asyncio
    async def test_save_result(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
        sample_result: ScreeningResult,
    ) -> None:
        """Test saving a screening result."""
        run_id = await repository.save_run(sample_stats, "ofi")
        result_id = await repository.save_result(sample_result, run_id)

        assert result_id > 0

    @pytest.mark.asyncio
    async def test_save_results(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
        sample_result: ScreeningResult,
    ) -> None:
        """Test saving multiple screening results."""
        run_id = await repository.save_run(sample_stats, "ofi")

        # Modify result for second symbol
        result2 = ScreeningResult(
            symbol="MSFT",
            timestamp=sample_result.timestamp,
            matches=True,
            signal_strength=0.8,
            conditions_met=["trend", "bounce"],
            conditions_missed=["oversold"],
            quote=sample_result.quote,
            indicators=sample_result.indicators,
            option_recommendation=sample_result.option_recommendation,
        )

        result_ids = await repository.save_results([sample_result, result2], run_id)

        assert len(result_ids) == 2

    @pytest.mark.asyncio
    async def test_get_results_by_symbol(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
        sample_result: ScreeningResult,
    ) -> None:
        """Test getting results by symbol."""
        run_id = await repository.save_run(sample_stats, "ofi")
        await repository.save_result(sample_result, run_id)

        results = await repository.get_results_by_symbol("AAPL", days=30)

        assert len(results) == 1
        assert results[0]["symbol"] == "AAPL"
        assert results[0]["matches"] is True

    @pytest.mark.asyncio
    async def test_get_recent_matches(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
        sample_result: ScreeningResult,
    ) -> None:
        """Test getting recent matches."""
        run_id = await repository.save_run(sample_stats, "ofi")
        await repository.save_result(sample_result, run_id)

        matches = await repository.get_recent_matches(days=30, limit=100)

        assert len(matches) == 1
        assert matches[0]["symbol"] == "AAPL"
        assert matches[0]["signal_strength"] == 1.0

    @pytest.mark.asyncio
    async def test_get_statistics(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
    ) -> None:
        """Test getting statistics."""
        await repository.save_run(sample_stats, "ofi")

        stats = await repository.get_statistics()

        assert stats["total_runs"] == 1
        assert stats["total_results"] == 0  # No results saved yet

    @pytest.mark.asyncio
    async def test_get_recent_runs(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
    ) -> None:
        """Test getting recent runs."""
        await repository.save_run(sample_stats, "ofi")

        runs = await repository.get_recent_runs(limit=10)

        assert len(runs) == 1
        assert runs[0]["strategy_name"] == "ofi"
        assert runs[0]["symbols_count"] == 10
        assert runs[0]["matches_count"] == 2

    @pytest.mark.asyncio
    async def test_quote_to_dict(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
        sample_result: ScreeningResult,
    ) -> None:
        """Test Quote model serialization."""
        run_id = await repository.save_run(sample_stats, "ofi")
        await repository.save_result(sample_result, run_id)

        results = await repository.get_results_by_symbol("AAPL", days=30)

        assert results[0]["quote_data"] is not None
        assert results[0]["quote_data"]["symbol"] == "AAPL"
        assert results[0]["quote_data"]["price"] == "185.50"

    @pytest.mark.asyncio
    async def test_indicators_to_dict(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
        sample_result: ScreeningResult,
    ) -> None:
        """Test TechnicalIndicators model serialization."""
        run_id = await repository.save_run(sample_stats, "ofi")
        await repository.save_result(sample_result, run_id)

        results = await repository.get_results_by_symbol("AAPL", days=30)

        assert results[0]["indicators_data"] is not None
        assert results[0]["indicators_data"]["sma_20"] == 185.0
        assert results[0]["indicators_data"]["rsi_14"] == 55.0

    @pytest.mark.asyncio
    async def test_option_recommendation_to_dict(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
        sample_result: ScreeningResult,
    ) -> None:
        """Test OptionRecommendation model serialization."""
        run_id = await repository.save_run(sample_stats, "ofi")
        await repository.save_result(sample_result, run_id)

        results = await repository.get_results_by_symbol("AAPL", days=30)

        assert results[0]["option_recommendation"] is not None
        assert results[0]["option_recommendation"]["strike"] == "180.00"
        assert results[0]["option_recommendation"]["premium_yield"] == 0.15

    @pytest.mark.asyncio
    async def test_row_to_match_dict(
        self,
        repository: ResultRepository,
        sample_stats: ScreeningStats,
        sample_result: ScreeningResult,
    ) -> None:
        """Test conversion of row to match dictionary."""
        run_id = await repository.save_run(sample_stats, "ofi")
        await repository.save_result(sample_result, run_id)

        matches = await repository.get_recent_matches(days=30, limit=100)

        assert len(matches) == 1
        assert matches[0]["symbol"] == "AAPL"
        assert matches[0]["signal_strength"] == 1.0
        assert matches[0]["option_strike"] == "180.00"
        assert matches[0]["premium_yield"] == 0.15
