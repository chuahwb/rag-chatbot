import pytest

from app.services.calculator import CalculatorError, CalculatorService


@pytest.fixture()
def service() -> CalculatorService:
    return CalculatorService()


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2", 3),
        ("3*(4+5)", 27),
        ("12.5 * (3 + 2) / 4", 15.625),
        ("2^3", 8),
        ("-5 + 10", 5),
    ],
)
def test_evaluate_valid_expressions(service: CalculatorService, expression: str, expected: float) -> None:
    result = service.evaluate(expression)

    assert result.expression == expression
    assert result.result == expected


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "2 +* 2",
        "abc + 1",
        "1 / (2 - 2)",
        "1 / 0",
    ],
)
def test_evaluate_invalid_expressions_raise_calculator_error(
    service: CalculatorService, expression: str
) -> None:
    with pytest.raises(CalculatorError):
        service.evaluate(expression)


def test_expression_length_limit(service: CalculatorService) -> None:
    long_expr = "1+" * 150  # 300 characters including operators
    with pytest.raises(CalculatorError):
        service.evaluate(long_expr)


def test_langchain_tool_invokes_service(service: CalculatorService) -> None:
    tool = service.langchain_tool

    result = tool.invoke("99 + 1")

    assert result == 100

