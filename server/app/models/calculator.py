from pydantic import BaseModel, Field


class CalculatorResult(BaseModel):
    expression: str = Field(..., description="The arithmetic expression that was evaluated.")
    result: float | int = Field(..., description="The evaluated numerical result.")



