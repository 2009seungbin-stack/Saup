"""Production-addressable file workflow; not a relabelled demo endpoint."""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from packages.domain.errors import DomainError
from packages.domain.order_intake import ImportConfirmation, VerifyImportedOrder, Market
from packages.domain.supplier_operations import Actor
from packages.integrations.marketplaces.order_file import template

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def create_order_intake_router(service, viewer, operator):
    router = APIRouter(prefix="/v1", tags=["order-intake"])
    def actor(user): return Actor(user["username"], user["role"])

    @router.get("/order-imports")
    def history(limit: int = Query(50, ge=1, le=100), user=Depends(viewer)):
        return service.history(limit)

    @router.get("/order-imports/template")
    def download_template(user=Depends(operator)):
        return Response(template(), media_type=MIME, headers={"Content-Disposition": 'attachment; filename="saup-orders-v1.xlsx"'})

    @router.get("/order-imports/catalog")
    def catalog(marketplace: Market, user=Depends(operator)):
        return Response(service.catalog_file(marketplace, actor(user)), media_type=MIME,
            headers={"Content-Disposition": 'attachment; filename="saup-listing-ids.xlsx"'})

    @router.post("/order-imports/preview")
    async def preview(marketplace: Market = Form(...), file: UploadFile = File(...), user=Depends(operator)):
        data = await file.read(service.c.settings.upload_max_bytes+1)
        return service.preview(data, marketplace, actor(user))

    @router.post("/order-imports/commit", status_code=201)
    async def commit(command: str = Form(..., max_length=5000), file: UploadFile = File(...), user=Depends(operator)):
        try:
            cmd = ImportConfirmation.model_validate_json(command)
        except ValidationError:
            raise DomainError("INVALID_ORDER_IMPORT_CONFIRMATION", 422) from None
        data = await file.read(service.c.settings.upload_max_bytes+1)
        return service.commit(data, cmd.model_dump(), actor(user))

    @router.get("/order-intake/pending")
    def pending(limit: int = Query(100, ge=1, le=200), user=Depends(operator)):
        return service.pending_orders(limit)

    @router.get("/order-intake/{order_id}")
    def details(order_id: str, user=Depends(operator)):
        return service.order_details(order_id)

    @router.post("/order-intake/{order_id}/verify-and-validate")
    def verify(order_id: str, data: VerifyImportedOrder, user=Depends(operator)):
        return service.verify_and_validate(order_id, data.model_dump(), actor(user))

    return router
