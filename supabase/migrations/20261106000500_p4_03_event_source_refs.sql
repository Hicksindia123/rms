-- Migration: 20261106000500_p4_03_event_source_refs.sql
-- Prompt: P4-03 (fix forward). Corrects the master-plan citations (source_ref) of notification
-- event types seeded by 20261106000300 / 20261106000400 so each one cites the governing rule.

update public.notification_event_types as t
   set source_ref = v.ref
  from (values
    ('GS_CREATED',               'BR-01'),
    ('REJECTION_RECORDED',       'BR-13, WF r5'),
    ('PENDENCY_OPENED',          'BR-20, G-08'),
    ('PENDENCY_CLEARED',         'BR-20, G-08'),
    ('TRANSFER_INITIATED',       'BR-21, G-09'),
    ('TRANSFER_DISCREPANCY',     'BR-21, G-09'),
    ('TRANSFER_ACCEPTED',        'BR-21, G-09'),
    ('TRANSFER_CANCELLED',       'G-09'),
    ('PARTS_RECOVERED',          'BR-27, BR-28'),
    ('STORE_ISSUED',             'BR-31'),
    ('DISPATCHED',               'BR-32'),
    ('CN_DECISION_REQUIRED',     'BR-32'),
    ('CN_DECISION_ALLOWED',      'BR-32'),
    ('CN_ISSUED',                'BR-37'),
    ('DAILY_AUDIT_MISSED',       'BR-18, DEC-08'),
    ('CONTAINER_AUDIT_REMINDER', 'BR-18, DEC-08'),
    ('TRANSFER_PROPOSED',        'BR-09, BR-10'),
    ('STOCK_ADJUSTMENT_REQUESTED','G-16, P3-04'),
    ('STOCK_ADJUSTMENT_DECIDED', 'G-16, P3-04'),
    ('NON_SELLABLE_RECEIVED',    'BR-25, DEC-17'),
    ('RM_ACTION_REVISED',        'BR-19, WF r6')
  ) as v(code, ref)
 where t.code = v.code;
