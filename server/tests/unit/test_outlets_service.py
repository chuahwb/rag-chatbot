import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import AppSettings
from app.db.base import Base
from app.db.models import Outlet
from app.services.outlets import (
    OutletsExecutionError,
    OutletsQueryError,
    OutletsText2SQLService,
    default_sql_generator,
    _build_sql_prompt,
    _prepare_text2sql_question,
)


@pytest.fixture(scope="module")
def engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine) -> Session:
    with Session(engine) as session:
        session.query(Outlet).delete()
        session.add_all(
            [
                Outlet(
                    external_id="zus-coffee-ss-2",
                    name="ZUS Coffee SS 2",
                    city="Petaling Jaya",
                    state="Selangor",
                    postal_code="47300",
                    address="No. 1, Jalan SS2/55, 47300 Petaling Jaya, Selangor",
                    open_time="09:00",
                    close_time="21:00",
                    services=["wifi", "delivery"],
                ),
                Outlet(
                    external_id="zus-coffee-uptown",
                    name="ZUS Coffee Uptown",
                    city="Petaling Jaya",
                    state="Selangor",
                    postal_code="47400",
                    address="123 Uptown Street, 47400 Petaling Jaya, Selangor",
                    open_time="08:00",
                    close_time="22:00",
                    services=["wifi"],
                ),
            ]
        )
        session.commit()
        yield session


def test_query_returns_rows(session: Session) -> None:
    def generator(_: str):
        return "SELECT name, open_time FROM outlets WHERE external_id = 'zus-coffee-ss-2'", {}

    service = OutletsText2SQLService(session=session, sql_generator=generator)

    response = service.query("opening time for SS 2")

    assert response.sql.lower().startswith("select")
    assert response.rows == [{"name": "ZUS Coffee SS 2", "open_time": "09:00"}]


def test_query_rejects_empty(session: Session) -> None:
    service = OutletsText2SQLService(session=session, sql_generator=lambda _: ("SELECT 1", {}))

    with pytest.raises(OutletsQueryError):
        service.query(" ")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM outlets; DROP TABLE outlets",
        "DELETE FROM outlets WHERE 1=1",
        "SELECT * FROM outlets -- comment",
    ],
)
def test_query_rejects_unsafe_sql(session: Session, sql: str) -> None:
    service = OutletsText2SQLService(session=session, sql_generator=lambda _: (sql, {}))

    with pytest.raises(OutletsQueryError):
        service.query("unsafe")


def test_query_rejects_non_select_sql(session: Session) -> None:
    service = OutletsText2SQLService(session=session, sql_generator=lambda _: ("DELETE FROM outlets", {}))

    with pytest.raises(OutletsQueryError):
        service.query("remove rows")


def test_query_handles_execution_error(session: Session) -> None:
    def generator(_: str):
        return "SELECT non_existing FROM outlets", {}

    service = OutletsText2SQLService(session=session, sql_generator=generator)

    with pytest.raises(OutletsExecutionError):
        service.query("bad column")


def test_query_allows_select_star_and_filters_columns(session: Session) -> None:
    def generator(_: str):
        return "SELECT * FROM outlets LIMIT 2;", {}

    service = OutletsText2SQLService(session=session, sql_generator=generator)

    response = service.query("show outlets")

    assert len(response.rows) <= OutletsText2SQLService.MAX_ROWS
    for row in response.rows:
        assert set(row.keys()).issubset(OutletsText2SQLService.ALLOWED_COLUMNS)


def test_query_strips_trailing_semicolon(session: Session) -> None:
    def generator(_: str):
        return "SELECT name FROM outlets;", {}

    service = OutletsText2SQLService(session=session, sql_generator=generator)

    response = service.query("show")

    assert response.rows


def test_default_sql_generator_requires_api_key(monkeypatch, session: Session) -> None:
    monkeypatch.setattr("app.services.outlets.get_settings", lambda: AppSettings(openai_api_key=None))

    with pytest.raises(OutletsExecutionError):
        default_sql_generator(session)


def test_default_sql_generator_uses_api_key(monkeypatch, session: Session) -> None:
    captured_kwargs: dict[str, object] = {}

    class DummyChatOpenAI:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    class DummyChain:
        def invoke(self, _: dict[str, str]) -> str:
            return "SELECT name FROM outlets"

    def fake_create_sql_query_chain(llm, db, **kwargs):
        captured_kwargs["llm"] = llm
        captured_kwargs["prompt"] = kwargs.get("prompt")
        captured_kwargs["top_k"] = kwargs.get("top_k")
        return DummyChain()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", DummyChatOpenAI)
    monkeypatch.setattr("langchain_community.utilities.SQLDatabase", lambda _: object())
    monkeypatch.setattr("langchain.chains.create_sql_query_chain", fake_create_sql_query_chain)
    monkeypatch.setattr("app.services.outlets.get_settings", lambda: AppSettings(openai_api_key="test-key"))

    generator = default_sql_generator(session)
    sql, params = generator("List outlets in PJ")

    assert captured_kwargs["api_key"] == "test-key"
    prompt = captured_kwargs["prompt"]
    assert prompt is not None
    assert set(prompt.input_variables) == {"input", "table_info", "top_k"}
    assert sql.startswith("SELECT")
    assert params == {}


def test_default_sql_generator_fake_provider(monkeypatch, session: Session) -> None:
    monkeypatch.setattr(
        "app.services.outlets.get_settings",
        lambda: AppSettings(text2sql_provider="fake"),
    )

    generator = default_sql_generator(session)
    sql, params = generator("Find SS2 outlets")

    assert sql.lower().startswith("select")
    assert "select *" not in sql.lower()
    assert "ss2" in sql.lower() or params  # ensures filtering applied


def test_default_sql_generator_fake_handles_aliases(monkeypatch, session: Session) -> None:
    monkeypatch.setattr(
        "app.services.outlets.get_settings",
        lambda: AppSettings(text2sql_provider="fake"),
    )

    generator = default_sql_generator(session)
    sql, params = generator("Any outlets near PJ?")

    assert "select" in sql.lower()
    assert params["name_param_0"] == "%petaling jaya%"
    assert params["city_param_1"] == "%petaling jaya%"


def test_default_sql_generator_local_provider(monkeypatch, session: Session) -> None:
    monkeypatch.setattr("app.services.outlets.get_settings", lambda: AppSettings(text2sql_provider="local"))

    captured_kwargs: dict[str, object] = {}

    class DummyChatOllama:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        def with_structured_output(self, schema):
            return self

        def invoke(self, prompt, **kwargs):
            return "SELECT name FROM outlets LIMIT 5"

    class DummyChain:
        def invoke(self, payload: dict[str, str]) -> str:
            return "SELECT name FROM outlets LIMIT 5"

    def fake_create_sql_query_chain(llm, db, **kwargs):
        captured_kwargs["llm_instance"] = llm
        captured_kwargs["prompt"] = kwargs.get("prompt")
        captured_kwargs["top_k"] = kwargs.get("top_k")
        return DummyChain()

    monkeypatch.setattr("langchain_community.chat_models.ChatOllama", DummyChatOllama)
    monkeypatch.setattr("langchain.chains.create_sql_query_chain", fake_create_sql_query_chain)
    monkeypatch.setattr("langchain_community.utilities.SQLDatabase", lambda _: object())

    generator = default_sql_generator(session)
    sql, params = generator("any query")

    assert sql.startswith("SELECT")
    assert params == {}
    assert captured_kwargs["model"] == AppSettings().text2sql_model
    prompt = captured_kwargs["prompt"]
    assert prompt is not None
    assert set(prompt.input_variables) == {"input", "table_info", "top_k"}


def test_build_sql_prompt_includes_required_fields() -> None:
    prompt = _build_sql_prompt()
    formatted = prompt.format(
        input="List outlets in Petaling Jaya",
        top_k=7,
        table_info="Table outlets(name TEXT)",
    )

    assert "Table outlets(name TEXT)" in formatted
    assert "List outlets in Petaling Jaya" in formatted
    assert "LIMIT 7" in formatted.upper()


def test_prepare_text2sql_question_adds_schema_hint() -> None:
    prepared = _prepare_text2sql_question("Any outlets near Petaling Jaya?")
    assert "columns name" in prepared.lower()
    assert "limit 10" in prepared.lower()
    assert "user question" in prepared.lower()
    assert "near petaling jaya" not in prepared.lower()
    assert "in petaling jaya" in prepared.lower()

