"""HTTP routes for the E-Commerce settlement (DEC-76). No SQL here (rule g).

Permissions (checked here and again by the DB triggers):
* ecommerce_unboxing.view / .create:        unboxing queue / unbox a batch, record repairs back
* ecommerce_store_receipts.view / .create:  store receipts / acknowledge (a user of that store)
* ecommerce_accounts.view / .edit:          action sheets / complete with the credit note
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.ecommerce_settlement.schemas import (
    AcknowledgeIn,
    ActionSheetListOut,
    ActionSheetOut,
    CompleteSheetIn,
    RepairReturnIn,
    ReturnSettlementOut,
    SheetStatus,
    StoreReceiptsOut,
    UnboxBatchIn,
    UnboxingQueueOut,
)
from app.modules.ecommerce_settlement.service import EcommerceSettlementService

router = APIRouter(prefix="/ecommerce-settlement", tags=["ecommerce-settlement"])

UnboxViewUser = Annotated[CurrentUser, Depends(require("ecommerce_unboxing", "view"))]
UnboxUser = Annotated[CurrentUser, Depends(require("ecommerce_unboxing", "create"))]
ReceiptViewUser = Annotated[CurrentUser, Depends(require("ecommerce_store_receipts", "view"))]
ReceiptUser = Annotated[CurrentUser, Depends(require("ecommerce_store_receipts", "create"))]
SheetViewUser = Annotated[CurrentUser, Depends(require("ecommerce_accounts", "view"))]
AccountsUser = Annotated[CurrentUser, Depends(require("ecommerce_accounts", "edit"))]


# --- unboxing ----------------------------------------------------------------------------------
@router.get("/unboxing", response_model=UnboxingQueueOut)
def unboxing_queue(user: UnboxViewUser, uow: UowDep) -> UnboxingQueueOut:
    """Returns waiting for unboxing (every platform, oldest first) and pieces still at repair."""
    return EcommerceSettlementService(uow).unboxing_queue(user)


@router.post("/unboxing", status_code=status.HTTP_201_CREATED, response_model=ActionSheetOut)
def unbox(
    payload: UnboxBatchIn, user: UnboxUser, uow: UowDep, idem: IdempotencyKeyDep
) -> JSONResponse:
    """Unbox a batch of ONE platform; creates its action sheet and moves the stock.
    `Idempotency-Key` required."""
    return EcommerceSettlementService(uow).unbox(user, payload, idem).to_response()


@router.post("/repairs/{repair_id}/return", response_model=ReturnSettlementOut)
def repair_return(
    repair_id: UUID,
    payload: RepairReturnIn,
    user: UnboxUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """Pieces back from repair: OK go to the store (acknowledgement), scrap to wastage."""
    return (
        EcommerceSettlementService(uow).repair_return(user, repair_id, payload, idem).to_response()
    )


# --- store receipts ----------------------------------------------------------------------------
@router.get("/store-receipts", response_model=StoreReceiptsOut)
def store_receipts(
    user: ReceiptViewUser,
    uow: UowDep,
    perms: EffectivePermissionsDep,
    state: Literal["PENDING", "ACKNOWLEDGED", "ALL"] = Query(default="PENDING"),
) -> StoreReceiptsOut:
    """Pieces issued to the user's stores (read-only roles see every store)."""
    return EcommerceSettlementService(uow).store_receipts(
        user, state, can_ack=perms.allows("ecommerce_store_receipts", "create")
    )


@router.post("/store-receipts/acknowledge", response_model=StoreReceiptsOut)
def acknowledge(
    payload: AcknowledgeIn, user: ReceiptUser, uow: UowDep, idem: IdempotencyKeyDep
) -> JSONResponse:
    """The store received the pieces: stock moves into the store. `Idempotency-Key` required."""
    return EcommerceSettlementService(uow).acknowledge(user, payload, idem).to_response()


# --- action sheets -----------------------------------------------------------------------------
@router.get("/action-sheets", response_model=ActionSheetListOut)
def action_sheets(
    user: SheetViewUser,
    uow: UowDep,
    status_code: Annotated[SheetStatus | None, Query(alias="status")] = None,
) -> ActionSheetListOut:
    return EcommerceSettlementService(uow).sheets(user, status_code)


@router.get("/action-sheets/{sheet_id}", response_model=ActionSheetOut)
def action_sheet(sheet_id: UUID, user: SheetViewUser, uow: UowDep) -> ActionSheetOut:
    """The sheet with every order id, Qty Received and Qty Issue CN (printable)."""
    return EcommerceSettlementService(uow).sheet(user, sheet_id)


@router.post("/action-sheets/{sheet_id}/complete", response_model=ActionSheetOut)
def complete_sheet(
    sheet_id: UUID,
    payload: CompleteSheetIn,
    user: AccountsUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """E-Commerce Accounts: the credit note (number, date, value) when Qty Issue CN > 0."""
    return (
        EcommerceSettlementService(uow).complete_sheet(user, sheet_id, payload, idem).to_response()
    )
