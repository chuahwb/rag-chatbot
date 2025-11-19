from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models.outlets import OutletsQueryResponse
from app.services.outlets import OutletsText2SQLService

router = APIRouter(prefix="/outlets", tags=["outlets"])


def get_outlets_service(session: Session = Depends(get_session)) -> OutletsText2SQLService:
    return OutletsText2SQLService.from_session(session)


@router.get("", response_model=OutletsQueryResponse)
async def query_outlets(
    query: str = Query(..., description="Natural language question about outlets."),
    service: OutletsText2SQLService = Depends(get_outlets_service),
) -> OutletsQueryResponse:
    return await service.query_async(query)


