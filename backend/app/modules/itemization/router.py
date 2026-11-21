"""Step-3 itemisation & CSR approval HTTP API (prompt P2-04). HTTP, auth and Pydantic I/O only."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.itemization.schemas import (
    CategorisationStateOut,
    CategorizeIn,
    CategorizeOut,
    CategoryLookup,
    CorrectionDecisionIn,
    CorrectionIn,
    CorrectionOut,
    CsrApprovalCard,
    CsrDecisionIn,
    ItemFieldsOut,
    ItemIn,
    ItemizationCommandOut,
    ItemizationStateOut,
    ItemOut,
    ItemPatchIn,
    LockedAddLineIn,
    LockedLineIn,
    LockedRemoveIn,
    LockIn,
    PackagingCheckIn,
    PackagingCheckOut,
    ProductLookup,
    ReopenIn,
    ReturnChoiceIn,
    SaveItemCategorisationIn,
)
from app.modules.itemization.service import ItemizationService

router = APIRouter(tags=["itemization"])


def get_service(uow: UowDep) -> ItemizationService:
    return ItemizationService(uow)


ServiceDep = Annotated[ItemizationService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("itemization", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("itemization", "create"))]
EditUser = Annotated[CurrentUser, Depends(require("itemization", "edit"))]
ApproveUser = Annotated[CurrentUser, Depends(require("itemization", "approve"))]
# DEC-64 d: edits after the categorisation lock (Super Admin, MANAGEMENT; seed.sql grants).
ConfigureUser = Annotated[CurrentUser, Depends(require("itemization", "configure"))]
GsViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]
StoreUser = Annotated[CurrentUser, Depends(require("inventory", "edit"))]


@router.get("/gs/{gs_id}/itemization", response_model=ItemizationStateOut)
def itemization_state(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> ItemizationStateOut:
    """Lines, category / decision options (from the published forms), stock lots, transfer,
    corrections, evidence and what the user may do."""
    return service.state(user, perms, gs_id)


@router.get("/itemization/lookups/products", response_model=list[ProductLookup])
def lookup_products(
    user: ViewUser,
    service: ServiceDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    category_id: UUID | None = None,
    subcategory_id: UUID | None = None,
) -> list[ProductLookup]:
    """Counting search: name / code / category / sub-category, optional filters (AMD-07)."""
    return service.products(user, q, limit, category_id=category_id, subcategory_id=subcategory_id)


@router.get("/itemization/lookups/categories", response_model=list[CategoryLookup])
def lookup_categories(user: ViewUser, service: ServiceDep) -> list[CategoryLookup]:
    """Category -> Sub-Category filters for the counting product search (AMD-07)."""
    return service.categories(user)


@router.get("/itemization/lookups/products/{product_id}/fields", response_model=ItemFieldsOut)
def lookup_product_fields(product_id: UUID, user: ViewUser, service: ServiceDep) -> ItemFieldsOut:
    """DEC-53: the condition buckets / item counts the line editor offers for a product."""
    return service.product_fields(user, product_id)


@router.post(
    "/gs/{gs_id}/itemization/return-choice",
    response_model=ItemizationCommandOut,
    responses={409: {"description": "Already chosen / not before the lock / idempotency"}},
)
def choose_return(
    gs_id: UUID,
    payload: ReturnChoiceIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DEC-64 (a, b): the popup after the item lines. RO (Replacement) → categorisation; CSR
    (Complete Sales Return) → SALES_RETURN_HOLD (Q11). Final; Idempotency-Key (G-16)."""
    return service.choose_return(user, perms, gs_id, payload, idem).to_response()


@router.post(
    "/gs/{gs_id}/categorisation/lock",
    response_model=ItemizationCommandOut,
    responses={409: {"description": "Not in categorisation / not Replacement / idempotency"}},
)
def lock_categorisation(
    gs_id: UUID,
    payload: LockIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DEC-64 (c), Q12: G-19 per line, inward stock into INWARD_STAGING (once), lock stamp,
    PENDING_TRANSFER_SLIP, RM notified; one transaction, Idempotency-Key (G-16)."""
    return service.lock(user, perms, gs_id, payload, idem).to_response()


@router.patch("/gs/{gs_id}/locked/items/{item_id}", response_model=ItemizationCommandOut)
def locked_update_line(
    gs_id: UUID,
    item_id: UUID,
    payload: LockedLineIn,
    user: ConfigureUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DEC-64 d: Super Admin / Management change qty, product or split after the lock (reason,
    revision, stock corrected in the same transaction), until the first routing."""
    return service.locked_update_line(user, perms, gs_id, item_id, payload, idem).to_response()


@router.post(
    "/gs/{gs_id}/locked/items",
    response_model=ItemizationCommandOut,
    status_code=status.HTTP_201_CREATED,
)
def locked_add_line(
    gs_id: UUID,
    payload: LockedAddLineIn,
    user: ConfigureUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DEC-64 d: add a line after the lock (split required, stock booked)."""
    return service.locked_add_line(user, perms, gs_id, payload, idem).to_response()


@router.post("/gs/{gs_id}/locked/items/{item_id}/remove", response_model=ItemizationCommandOut)
def locked_remove_line(
    gs_id: UUID,
    item_id: UUID,
    payload: LockedRemoveIn,
    user: ConfigureUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DEC-64 d: remove a line after the lock (stocked lines stay as history with qty 0)."""
    return service.locked_remove_line(user, perms, gs_id, item_id, payload, idem).to_response()


@router.post(
    "/gs/{gs_id}/counting/submit",
    response_model=ItemizationStateOut,
    responses={409: {"description": "Counting already submitted / idempotency conflict"}},
)
def submit_counting(
    gs_id: UUID,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """AMD-08: Counting (ITEMIZATION) -> CATEGORISATION with >= 1 line (Idempotency-Key, G-16)."""
    return service.submit_counting(user, perms, gs_id, idem).to_response()


@router.post("/gs/{gs_id}/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def add_item(
    gs_id: UUID,
    payload: ItemIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> ItemOut:
    """Add a line while ITEMIZATION (S1_ITEMIZE PERFORM). Short / excess are computed."""
    return service.add_item(user, perms, gs_id, payload)


@router.patch("/gs/{gs_id}/items/{item_id}", response_model=ItemOut)
def update_item(
    gs_id: UUID,
    item_id: UUID,
    payload: ItemPatchIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> ItemOut:
    return service.update_item(user, perms, gs_id, item_id, payload)


@router.delete("/gs/{gs_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    gs_id: UUID, item_id: UUID, user: EditUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> Response:
    service.delete_item(user, perms, gs_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/gs/{gs_id}/categorize",
    response_model=CategorizeOut,
    responses={409: {"description": "Already categorised / idempotency conflict"}},
)
def categorize(
    gs_id: UUID,
    payload: CategorizeIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """BR-07: GS-wise CSR | RO; inwards every line into INWARD_STAGING (`Idempotency-Key`)."""
    return service.categorize(user, perms, gs_id, payload, idem).to_response()


@router.get("/gs/{gs_id}/categorisation", response_model=CategorisationStateOut)
def categorisation_state(
    gs_id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> CategorisationStateOut:
    """AMD-09 / AMD-11: Fetch per-item categorisation buckets, counts and conservation state."""
    return service.get_categorisation_state(user, perms, gs_id)


@router.put("/gs/{gs_id}/items/{item_id}/categorisation")
def save_item_categorisation(
    gs_id: UUID,
    item_id: UUID,
    payload: SaveItemCategorisationIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """AMD-09 / AMD-11: Save per-item bucket quantities and container/packaging/manual counts."""
    return service.save_item_categorisation(
        user, perms, gs_id, item_id, payload, idem
    ).to_response()


@router.post("/gs/{gs_id}/csr-decision", response_model=ItemizationStateOut)
def csr_decision(
    gs_id: UUID,
    payload: CsrDecisionIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """G-03 / BR-08 / BR-09: Replacement Manager approves or rejects (reason) a CSR, once."""
    return service.decide(user, perms, gs_id, payload, idem).to_response()


@router.post("/gs/{gs_id}/csr-decision/reopen", response_model=ItemizationStateOut)
def reopen_csr_decision(
    gs_id: UUID,
    payload: ReopenIn,
    user: GsViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> ItemizationStateOut:
    """Admin only, with reason, while nothing downstream has happened."""
    return service.reopen(user, perms, gs_id, payload)


@router.get("/csr-approvals/pending", response_model=list[CsrApprovalCard])
def pending_csr_approvals(
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[CsrApprovalCard]:
    """Replacement Manager inbox: GS summary, lines and evidence per pending CSR."""
    return service.pending_csr(user, perms, limit)


@router.post(
    "/gs/{gs_id}/items/{item_id}/corrections",
    response_model=CorrectionOut,
    status_code=status.HTTP_201_CREATED,
)
def request_correction(
    gs_id: UUID,
    item_id: UUID,
    payload: CorrectionIn,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> CorrectionOut:
    """Post-categorisation line edit request (reason); the RM approves it."""
    return service.request_correction(user, perms, gs_id, item_id, payload)


@router.post("/gs/{gs_id}/item-corrections/{correction_id}/decision", response_model=CorrectionOut)
def decide_correction(
    gs_id: UUID,
    correction_id: UUID,
    payload: CorrectionDecisionIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """Approve (applies the line + ADJUST movement) or reject (reason). `Idempotency-Key`."""
    return service.decide_correction(user, perms, gs_id, correction_id, payload, idem).to_response()


@router.get("/item-corrections/pending", response_model=list[CorrectionOut])
def pending_corrections(
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[CorrectionOut]:
    return service.pending_corrections(user, perms, limit)


@router.post(
    "/lots/{lot_id}/packaging-check",
    response_model=PackagingCheckOut,
    status_code=status.HTTP_201_CREATED,
)
def packaging_check(
    lot_id: UUID,
    payload: PackagingCheckIn,
    user: StoreUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> PackagingCheckOut:
    """WF r4 / BR-10 / DEC-27: Intermediate Store in-charge records OK or REPLACED (+ qty)."""
    return service.packaging_check(user, perms, lot_id, payload)
