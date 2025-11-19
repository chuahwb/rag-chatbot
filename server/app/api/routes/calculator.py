from fastapi import APIRouter, Depends, Query

from app.models.calculator import CalculatorResult
from app.services.calculator import CalculatorService

router = APIRouter(tags=["calculator"])


def get_calculator_service() -> CalculatorService:
    return CalculatorService()


@router.get("/calc", response_model=CalculatorResult)
async def evaluate_calculator_expression(
    query: str = Query(..., description="Arithmetic expression to evaluate."),
    service: CalculatorService = Depends(get_calculator_service),
) -> CalculatorResult:
    return service.evaluate(query)



