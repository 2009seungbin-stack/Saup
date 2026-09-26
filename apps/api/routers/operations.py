"""Real /v1 operations; all mutations inherit session Origin/CSRF enforcement."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from packages.domain import operations as inputs
from packages.domain.marketplace_cancellation import CancellationStatementCorrection
from packages.domain.supplier_operations import Actor
from packages.infrastructure.models import User, Claim, AuditEvent
from packages.application.operations import Operations, safe, get
from packages.application.review_resolution import ReviewResolutionService


def create_operations_router(commerce, viewer, operator, admin):
    router = APIRouter(prefix='/v1', tags=['operations'])
    service = Operations(commerce)
    def actor(user): return Actor(user['username'], user['role'])

    @router.get('/setup')
    def setup(user=Depends(viewer)): return service.setup_view()

    @router.get('/operations')
    def operations(user=Depends(viewer)): return service.work_view()

    @router.get('/users')
    def users(user=Depends(admin)):
        with commerce.factory() as s: return [safe(x, 'id username role active') for x in s.scalars(select(User))]

    @router.post('/users')
    def create_user(data: inputs.UserInput, user=Depends(admin)): return service.create_user(data, actor(user))

    @router.post('/suppliers')
    def supplier(data: inputs.SupplierInput, user=Depends(admin)): return service.supplier(data, actor(user))

    @router.put('/suppliers/{supplier_id}')
    def update_supplier(supplier_id: str, data: inputs.SupplierInput, user=Depends(admin)):
        return service.supplier(data, actor(user), supplier_id)

    @router.post('/listings')
    def listing(data: inputs.ListingInput, user=Depends(operator)): return service.create_listing(data, actor(user))

    @router.post('/listings/{listing_id}/external-activation')
    def activate(listing_id: str, data: inputs.ListingActivation, user=Depends(operator)):
        return service.activate_listing(listing_id, data, actor(user))

    @router.post('/funds/opening-bank')
    def opening(data: inputs.FundsInput, user=Depends(admin)): return service.funds(data, actor(user))

    @router.post('/suppliers/{supplier_id}/deposit')
    def deposit(supplier_id: str, data: inputs.FundsInput, user=Depends(admin)): return service.funds(data, actor(user), supplier_id)

    @router.post('/shipments/{shipment_id}/external-confirmation')
    def shipment(shipment_id: str, data: inputs.ShipmentConfirmation, user=Depends(operator)):
        return service.confirm_shipment(shipment_id, data, actor(user))

    @router.post('/orders/{order_id}/delivery-confirmation')
    def delivery(order_id: str, data: inputs.Evidence, user=Depends(operator)): return service.delivered(order_id, data, actor(user))

    @router.post('/orders/{order_id}/claims')
    def claim(order_id: str, data: inputs.ClaimInput, user=Depends(operator)): return service.claim(order_id, data, actor(user))

    @router.get('/claims/{claim_id}')
    def detail(claim_id: str, user=Depends(viewer)):
        with commerce.factory() as s:
            row = get(s, Claim, claim_id)
            view = service.work_view()
            return {'claim': safe(row, 'id order_id category status requested_amount customer_refund supplier_recovery'),
                'refunds': [x for x in view['refunds'] if x['claim_id'] == row.id],
                'receipts': [x for x in view['receipts'] if x['target_id'] in {row.id, *(r['id'] for r in view['refunds'] if r['claim_id'] == row.id)}],
                'history': [safe(x, 'id event actor created_at new_value') for x in s.scalars(select(AuditEvent).where(AuditEvent.entity_id == row.id))]}

    @router.post('/claims/{claim_id}/supplier-response')
    def response(claim_id: str, data: inputs.ClaimResponse, user=Depends(operator)): return service.response(claim_id, data, actor(user))

    @router.post('/claims/{claim_id}/supplier-recovery')
    def recovery(claim_id: str, data: inputs.FundsInput, user=Depends(admin)): return service.recovery(claim_id, data, actor(user))

    @router.post('/claims/{claim_id}/refunds')
    def request_refund(claim_id: str, data: inputs.RefundRequest, user=Depends(admin)): return service.request_refund(claim_id, data, actor(user))

    @router.post('/refunds/{refund_id}/external-confirmation')
    def confirm_refund(refund_id: str, data: inputs.RefundConfirmation, user=Depends(admin)): return service.confirm_refund(refund_id, data, actor(user))

    @router.post('/orders/{order_id}/settlement')
    def statement(order_id: str, data: inputs.SettlementInput, user=Depends(operator)): return service.settlement(order_id, data, actor(user))

    @router.post('/settlements/{settlement_id}/cash-confirmation')
    def cash(settlement_id: str, data: inputs.CashConfirmation, user=Depends(admin)): return service.settlement_cash(settlement_id, data, actor(user))

    @router.post('/settlements/{settlement_id}/corrections')
    def correction(settlement_id: str, data: inputs.SettlementCorrection, user=Depends(admin)): return service.correct_settlement(settlement_id, data, actor(user))

    @router.post('/reviews/{review_id}/marketplace-statement-corrections')
    def cancellation_correction(review_id: str, data: CancellationStatementCorrection, user=Depends(admin)):
        return ReviewResolutionService(commerce).marketplace.correct_statement(review_id, data, actor(user))

    return router
