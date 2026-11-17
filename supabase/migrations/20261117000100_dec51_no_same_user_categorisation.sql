-- DEC-51 (2026-11-17, business decision): no task-ownership lock between workflow steps.
-- Any user eligible for a step (role permission) may perform it on any GS at that step, whoever
-- performed the previous step. goods_slips.counted_by is kept for audit / display only; it is
-- not enforced in the database (never was) and no longer in the backend service.
comment on column public.goods_slips.counted_by is
  'AMD-08: profile ID of the user who submitted counting. Audit / display only (DEC-51): any eligible inward verifier may categorise.';
