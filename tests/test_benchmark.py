"""Tests for AlfaHRBenchmark service and API."""

import io
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services.benchmark_service import (
    _avg_salary,
    _convert_to_byn,
    _round_salary,
    _safe_float,
    _salary_gross_to_net,
    _salary_lower_bound,
    _salary_net_to_gross,
    clean_for_json,
    export_to_excel,
    filter_outliers_and_compute_stats,
    to_table_records,
)


# ---- Helper function tests ----

class TestSafeFloat:
    def test_none(self):
        assert _safe_float(None) is None

    def test_normal(self):
        assert _safe_float(1500.5) == 1500.5

    def test_inf(self):
        assert _safe_float(float("inf")) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_string(self):
        assert _safe_float("not_a_number") is None

    def test_zero(self):
        assert _safe_float(0) == 0.0


class TestConvertToByn:
    def test_byn_passthrough(self):
        assert _convert_to_byn(1000, "BYN", {}) == 1000

    def test_byr_passthrough(self):
        assert _convert_to_byn(1000, "BYR", {}) == 1000

    def test_usd_conversion(self):
        rates = {"USD": 3.0}
        assert _convert_to_byn(100, "USD", rates) == 300

    def test_unknown_currency(self):
        assert _convert_to_byn(100, "XYZ", {"USD": 3.0}) is None

    def test_none_amount(self):
        assert _convert_to_byn(None, "USD", {"USD": 3.0}) is None

    def test_none_currency(self):
        assert _convert_to_byn(100, None, {"USD": 3.0}) is None


class TestSalaryConversion:
    def test_gross_to_net(self):
        result = _salary_gross_to_net(1000)
        assert result == pytest.approx(860.0)

    def test_net_to_gross(self):
        result = _salary_net_to_gross(860)
        assert result == pytest.approx(1000.0, rel=0.01)

    def test_net_to_gross_zero(self):
        assert _salary_net_to_gross(0) is None


class TestAvgSalary:
    def test_both_values(self):
        assert _avg_salary(1000, 2000) == 1500

    def test_only_from(self):
        assert _avg_salary(1000, None) == 1000

    def test_only_to(self):
        assert _avg_salary(None, 2000) == 2000

    def test_both_none(self):
        assert _avg_salary(None, None) is None


class TestSalaryLowerBound:
    def test_both(self):
        assert _salary_lower_bound(1000, 2000) == 1000

    def test_only_from(self):
        assert _salary_lower_bound(1500, None) == 1500

    def test_both_none(self):
        assert _salary_lower_bound(None, None) is None


class TestRoundSalary:
    def test_normal(self):
        assert _round_salary(1500.7) == 1501

    def test_none(self):
        assert _round_salary(None) is None


class TestCleanForJson:
    def test_nested(self):
        data = {"a": float("inf"), "b": [1, float("nan"), None], "c": 42}
        result = clean_for_json(data)
        assert result == {"a": None, "b": [1, None, None], "c": 42}

    def test_plain(self):
        assert clean_for_json(3.14) == 3.14


# ---- Filter & stats tests ----

class TestFilterOutliersAndComputeStats:
    def _make_row(self, gross_from, gross_to, net_from=None, net_to=None):
        return {
            "salary_gross_from_byn": gross_from,
            "salary_gross_to_byn": gross_to,
            "salary_net_from_byn": net_from or (gross_from * 0.86 if gross_from else None),
            "salary_net_to_byn": net_to or (gross_to * 0.86 if gross_to else None),
            "logo_url": None, "name": "Test", "employer_name": "Co",
            "area_name": "Minsk", "specialization": "", "experience": "",
            "published_at": "", "loaded_at": "", "url": "",
        }

    def test_empty(self):
        filtered, stats, avg_g, avg_n = filter_outliers_and_compute_stats([])
        assert stats["count"] == 0
        assert filtered == []

    def test_filters_below_minimum(self):
        rows = [
            self._make_row(100, 200),  # below 500 threshold
            self._make_row(2000, 3000),
            self._make_row(2500, 3500),
        ]
        filtered, stats, _, _ = filter_outliers_and_compute_stats(rows)
        assert all(
            r["salary_gross_from_byn"] >= 500 or r["salary_gross_from_byn"] is None
            for r in filtered
        )

    def test_stats_computed(self):
        rows = [self._make_row(1000, 2000) for _ in range(5)]
        filtered, stats, avg_g, avg_n = filter_outliers_and_compute_stats(rows)
        assert stats["count"] == 5
        assert stats["min"] is not None
        assert stats["max"] is not None
        assert stats["mean"] is not None
        assert stats["median"] is not None
        assert len(avg_g) == 5
        assert len(avg_n) == 5


# ---- Table formatting tests ----

class TestToTableRecords:
    def test_rounds_salaries(self):
        rows = [{
            "logo_url": None, "name": "Dev", "employer_name": "Co",
            "area_name": "Minsk", "specialization": "IT", "experience": "3 years",
            "salary_net_from_byn": 1234.5, "salary_net_to_byn": 2345.6,
            "salary_gross_from_byn": 1435.5, "salary_gross_to_byn": 2727.4,
            "url": "http://example.com", "published_at": "01.01.2026", "loaded_at": "01.01.2026",
        }]
        result = to_table_records(rows)
        assert result[0]["salary_net_from_byn"] == 1234
        assert result[0]["salary_gross_to_byn"] == 2727


# ---- Excel export test ----

class TestExportToExcel:
    def test_produces_xlsx(self):
        rows = [{
            "logo_url": None, "name": "Dev", "employer_name": "Co",
            "area_name": "Minsk", "specialization": "IT", "experience": "",
            "salary_net_from_byn": 1000, "salary_net_to_byn": 2000,
            "salary_gross_from_byn": 1163, "salary_gross_to_byn": 2326,
            "url": "http://example.com", "published_at": "01.01.2026", "loaded_at": "01.01.2026",
        }]
        output = export_to_excel(rows)
        assert isinstance(output, io.BytesIO)
        content = output.read()
        assert len(content) > 100


# ---- API endpoint tests ----

class TestBenchmarkAPINoAuth:
    """Benchmark endpoints require authentication."""

    def test_search_unauthenticated(self, client):
        resp = client.post(
            "/api/benchmark/search",
            json={"include": "python"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_export_unauthenticated(self, client):
        resp = client.post(
            "/api/benchmark/export-excel",
            json={"include": "python"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_rates_unauthenticated(self, client):
        resp = client.get(
            "/api/benchmark/rates",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401


class TestBenchmarkAPIAuth:
    """Benchmark endpoints with authentication."""

    def test_search_empty_query(self, client, user_session_token):
        resp = client.post(
            "/api/benchmark/search",
            json={"include": ""},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400

    def test_search_with_mocked_hh(self, client, user_session_token):
        with patch(
            "app.api.benchmark.fetch_vacancies", new_callable=AsyncMock, return_value=[]
        ):
            resp = client.post(
                "/api/benchmark/search",
                json={"include": "python developer"},
                cookies={"session_token": user_session_token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["table"] == []
            assert data["stats"]["count"] == 0

    def test_export_empty_results(self, client, user_session_token):
        with patch(
            "app.api.benchmark.fetch_vacancies", new_callable=AsyncMock, return_value=[]
        ), patch(
            "app.api.benchmark.process_vacancies_data", new_callable=AsyncMock, return_value=[]
        ):
            resp = client.post(
                "/api/benchmark/export-excel",
                json={"include": "python developer"},
                cookies={"session_token": user_session_token},
            )
            assert resp.status_code == 404


class TestBenchmarkPage:
    """Page endpoint tests."""

    def test_benchmark_page_renders(self, client):
        resp = client.get("/benchmark")
        assert resp.status_code == 200
        assert "AlfaHRBenchmark" in resp.text
        assert "salaryChart" in resp.text
