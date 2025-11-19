from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from functools import cached_property

from langchain_core.tools import tool

from app.core.exceptions import AppError
from app.models.calculator import CalculatorResult


class CalculatorError(AppError):
    status_code = 400
    error_type = "CALCULATOR_ERROR"


@dataclass
class _EvaluationResult:
    value: float

    def as_number(self) -> int | float:
        if self.value.is_integer():
            return int(self.value)
        return self.value


class CalculatorService:
    MAX_EXPRESSION_LENGTH = 200

    _BINARY_OPERATORS: dict[type[ast.AST], callable] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    _UNARY_OPERATORS: dict[type[ast.AST], callable] = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def evaluate(self, expression: str) -> CalculatorResult:
        cleaned = expression.strip()
        if not cleaned:
            raise CalculatorError("Expression cannot be empty.")

        if len(cleaned) > self.MAX_EXPRESSION_LENGTH:
            raise CalculatorError(f"Expression exceeds {self.MAX_EXPRESSION_LENGTH} characters.")

        normalized = self._normalize_expression(cleaned)

        try:
            syntax_tree = ast.parse(normalized, mode="eval")
        except SyntaxError as exc:
            raise CalculatorError("Invalid arithmetic expression.") from exc

        try:
            result = self._evaluate_node(syntax_tree.body)
        except ZeroDivisionError as exc:
            raise CalculatorError("Division by zero is not allowed.") from exc

        return CalculatorResult(
            expression=expression,
            result=result.as_number(),
        )

    @cached_property
    def langchain_tool(self):
        service = self

        @tool("calculator", return_direct=True)
        def _calculator(expression: str) -> int | float:
            """Evaluate a mathematical expression and return the numeric result."""
            return service.evaluate(expression).result

        return _calculator

    def _normalize_expression(self, expression: str) -> str:
        # Allow caret for exponentiation by translating to Python's power operator.
        return expression.replace("^", "**")

    def _evaluate_node(self, node: ast.AST) -> _EvaluationResult:
        if isinstance(node, ast.BinOp):
            operator_fn = self._BINARY_OPERATORS.get(type(node.op))
            if operator_fn is None:
                raise CalculatorError("Unsupported operator in expression.")

            left = self._evaluate_node(node.left)
            right = self._evaluate_node(node.right)
            value = operator_fn(left.value, right.value)
            return _EvaluationResult(float(value))

        if isinstance(node, ast.UnaryOp):
            operator_fn = self._UNARY_OPERATORS.get(type(node.op))
            if operator_fn is None:
                raise CalculatorError("Unsupported unary operator in expression.")
            operand = self._evaluate_node(node.operand)
            value = operator_fn(operand.value)
            return _EvaluationResult(float(value))

        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                raise CalculatorError("Boolean values are not supported.")
            if not isinstance(node.value, (int, float)):
                raise CalculatorError("Expression contains unsupported literals.")
            return _EvaluationResult(float(node.value))

        if isinstance(node, ast.Expr):
            return self._evaluate_node(node.value)

        raise CalculatorError("Expression contains unsupported elements.")


