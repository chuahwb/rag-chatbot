from fastapi import APIRouter, Depends, Query

from app.models.products import ProductSearchResponse
from app.services.products import ProductSearchService

router = APIRouter(prefix="/products", tags=["products"])


def get_product_search_service() -> ProductSearchService:
    return ProductSearchService.from_settings()


@router.get("", response_model=ProductSearchResponse)
async def search_products(
    query: str = Query(..., description="User query about drinkware products."),
    k: int = Query(3, ge=1, le=10, description="Number of top documents to return."),
    service: ProductSearchService = Depends(get_product_search_service),
) -> ProductSearchResponse:
    return await service.search_async(query, k=k)


