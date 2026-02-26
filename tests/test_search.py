"""Tests for search-related logic (unit tests, no external API calls)."""

import pytest
from app.services.hh_service import (
    build_params,
    format_experience,
    format_salary,
    parse_item,
)


class TestFormatExperience:
    def test_none(self):
        assert format_experience(None) == "—"

    def test_zero(self):
        assert format_experience(0) == "< 1 мес."

    def test_months_only(self):
        assert format_experience(5) == "5 мес."

    def test_years_only(self):
        assert format_experience(24) == "2 г."

    def test_years_and_months(self):
        assert format_experience(26) == "2 г. 2 мес."


class TestFormatSalary:
    def test_none(self):
        assert format_salary(None) == "—"

    def test_empty_dict(self):
        assert format_salary({}) == "—"

    def test_no_amount(self):
        assert format_salary({"currency": "RUR"}) == "—"

    def test_rur(self):
        result = format_salary({"amount": 150000, "currency": "RUR"})
        assert "150" in result
        assert "₽" in result

    def test_usd(self):
        result = format_salary({"amount": 5000, "currency": "USD"})
        assert "5" in result
        assert "$" in result


class TestParseItem:
    def test_full_item(self):
        item = {
            "first_name": "Иван",
            "last_name": "Петров",
            "middle_name": "Сергеевич",
            "title": "Python Developer",
            "photo": {"small": "http://photo.jpg"},
            "area": {"name": "Минск"},
            "total_experience": {"months": 36},
            "salary": {"amount": 3000, "currency": "USD"},
            "alternate_url": "https://hh.ru/resume/123",
            "updated_at": "2026-01-15",
            "id": "12345",
        }
        result = parse_item(item)
        assert result["source"] == "hh"
        assert result["full_name"] == "Петров Иван Сергеевич"
        assert result["title"] == "Python Developer"
        assert result["area"] == "Минск"
        assert result["photo"] == "http://photo.jpg"
        assert "3 г." in result["experience"]
        assert result["external_id"] == "12345"

    def test_minimal_item(self):
        result = parse_item({})
        assert result["full_name"] == "—"
        assert result["source"] == "hh"


class TestBuildParams:
    def test_basic_search(self):
        params = build_params(
            search_text="Python",
            search_in_positions=False,
            search_skills="",
            search_skills_field="skills",
            search_company="",
            exclude_title="",
            exclude_company="",
            experience=[],
            area=16,
            period=30,
            page=0,
            per_page=50,
        )
        param_dict = dict(params)
        assert ("text", "Python") in params
        assert param_dict["area"] == "16"
        assert param_dict["per_page"] == "50"

    def test_skills_added(self):
        params = build_params(
            search_text="",
            search_in_positions=False,
            search_skills="FastAPI, Docker",
            search_skills_field="skills",
            search_company="",
            exclude_title="",
            exclude_company="",
            experience=[],
            area=1002,
            period=7,
            page=0,
            per_page=20,
        )
        texts = [v for k, v in params if k == "text"]
        assert "FastAPI Docker" in texts  # запятые заменяются на пробелы

    def test_exclude_fields(self):
        params = build_params(
            search_text="Developer",
            search_in_positions=True,
            search_skills="",
            search_skills_field="skills",
            search_company="",
            exclude_title="Manager",
            exclude_company="Google",
            experience=["between3And6"],
            area=16,
            period=30,
            page=0,
            per_page=50,
        )
        texts = [v for k, v in params if k == "text"]
        assert "Manager" in texts
        assert "Google" in texts
        logics = [v for k, v in params if k == "text.logic"]
        assert "except" in logics
        experiences = [v for k, v in params if k == "experience"]
        assert "between3And6" in experiences

    def test_search_company_added(self):
        params = build_params(
            search_text="",
            search_in_positions=False,
            search_skills="",
            search_skills_field="skills",
            search_company="Epam",
            exclude_title="",
            exclude_company="",
            experience=[],
            area=16,
            period=30,
            page=0,
            per_page=50,
        )
        param_dict = dict(params)
        field_vals = [v for k, v in params if k == "text.field"]
        assert "experience_company" in field_vals
        texts = [v for k, v in params if k == "text"]
        assert "Epam" in texts

    def test_skills_field_everywhere(self):
        params = build_params(
            search_text="",
            search_in_positions=False,
            search_skills="Python",
            search_skills_field="everywhere",
            search_company="",
            exclude_title="",
            exclude_company="",
            experience=[],
            area=16,
            period=30,
            page=0,
            per_page=50,
        )
        field_vals = [v for k, v in params if k == "text.field"]
        assert "everywhere" in field_vals


class TestNormalizeSources:
    def test_normalize(self):
        from app.api.search import _normalize_sources
        assert _normalize_sources("hh") == (True, False)
        assert _normalize_sources("linkedin") == (False, True)
        assert _normalize_sources("both") == (True, True)
        assert _normalize_sources("") == (True, True)
        assert _normalize_sources("BOTH") == (True, True)
