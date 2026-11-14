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
    ItemIn,
    ItemizationStateOut,
    ItemOut,
    ItemPatchIn,
    PackagingCheckIn,
    PackagingCheckOut,
    ProductLookup,
    ReopenIn,
    SaveItemCategorisationIn,
    SubmitCategorisationIn,
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


@router.post("/gs/{gs_id}/categorisation/submit")
def submit_categorisation(
    gs_id: UUID,
    payload: SubmitCategorisationIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """AMD-11 / G-19: Submit item categorisation;
    enforces sum(bucket) = received_qty -> RM_REVIEW.
    """
    return service.submit_categorisation(user, perms, gs_id, payload, idem).to_response()


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
