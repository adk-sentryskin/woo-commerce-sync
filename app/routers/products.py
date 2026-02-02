from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.database import get_db
from app.models import Product, WooCommerceStore
from app.schemas import ProductResponse, ProductListResponse
from app.middleware.auth import verify_api_key, get_merchant_from_header
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["Products"])


@router.get("", response_model=ProductListResponse)
async def list_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    store: WooCommerceStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    query = db.query(Product).filter(Product.merchant_id == store.merchant_id)

    if not include_deleted:
        query = query.filter(Product.is_deleted == 0)
    if status:
        query = query.filter(Product.status == status)
    if type:
        query = query.filter(Product.type == type)
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(Product.name.ilike(search_term), Product.sku.ilike(search_term), Product.slug.ilike(search_term)))

    total = query.count()
    total_pages = (total + per_page - 1) // per_page
    offset = (page - 1) * per_page
    products = query.order_by(Product.wc_product_id.desc()).offset(offset).limit(per_page).all()

    return ProductListResponse(
        products=[ProductResponse.model_validate(p) for p in products],
        total=total, page=page, per_page=per_page, total_pages=total_pages
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    store: WooCommerceStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    product = db.query(Product).filter(Product.wc_product_id == product_id, Product.merchant_id == store.merchant_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    return ProductResponse.model_validate(product)


@router.get("/by-sku/{sku}", response_model=ProductResponse)
async def get_product_by_sku(
    sku: str,
    store: WooCommerceStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    product = db.query(Product).filter(Product.sku == sku, Product.merchant_id == store.merchant_id, Product.is_deleted == 0).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product with SKU '{sku}' not found")
    return ProductResponse.model_validate(product)


@router.get("/search/semantic")
async def semantic_search(
    query: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    store: WooCommerceStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    from app.config import settings

    if not settings.ENABLE_EMBEDDINGS:
        raise HTTPException(status_code=400, detail="Semantic search is not enabled")

    try:
        from app.services.embedding_service import get_embedding_service
        emb_service = get_embedding_service()
        query_embedding = emb_service.generate_embedding(query)

        results = db.query(Product).filter(
            Product.merchant_id == store.merchant_id,
            Product.is_deleted == 0,
            Product.embedding.isnot(None)
        ).order_by(Product.embedding.l2_distance(query_embedding)).limit(limit).all()

        return {
            "query": query,
            "results": [{"id": p.id, "wc_product_id": p.wc_product_id, "name": p.name, "sku": p.sku, "price": p.price, "status": p.status} for p in results],
            "total": len(results)
        }
    except ImportError:
        raise HTTPException(status_code=500, detail="Embedding service not available")
    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/stats/summary")
async def get_product_stats(
    store: WooCommerceStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    from sqlalchemy import func

    total = db.query(Product).filter(Product.merchant_id == store.merchant_id).count()
    active = db.query(Product).filter(Product.merchant_id == store.merchant_id, Product.is_deleted == 0).count()

    status_counts = db.query(Product.status, func.count(Product.id)).filter(
        Product.merchant_id == store.merchant_id, Product.is_deleted == 0
    ).group_by(Product.status).all()

    type_counts = db.query(Product.type, func.count(Product.id)).filter(
        Product.merchant_id == store.merchant_id, Product.is_deleted == 0
    ).group_by(Product.type).all()

    return {
        "merchant_id": store.merchant_id, "total_products": total, "active_products": active,
        "deleted_products": total - active,
        "by_status": {status: count for status, count in status_counts if status},
        "by_type": {ptype: count for ptype, count in type_counts if ptype},
        "last_synced_at": store.last_synced_at
    }
