-- P1-02 pgTAP: rms_private.next_number (DEC-01; master plan §8.3 number_series).
begin;
create extension if not exists pgtap with schema extensions;
select plan(21);

-- Independent of local data: start from empty counters (rolled back with the test).
delete from public.number_series_counters
 where series_id in (select id from public.number_series where code in ('GS', 'TRANSFER'));

-- GS placeholder pattern GS/{FY}/{SEQ:5}, FY starts in April, LONG format ("2026-27").
select is(rms_private.next_number('GS', '2026-05-15'), 'GS/2026-27/00001', 'first GS number of FY 2026-27');
select is(rms_private.next_number('GS', '2026-11-02'), 'GS/2026-27/00002', 'sequential within the FY');
select is(rms_private.next_number('GS', '2027-03-31'), 'GS/2026-27/00003', '31 March is still FY 2026-27');
select is(rms_private.next_number('GS', '2027-04-01'), 'GS/2027-28/00001', 'counter resets on 1 April (new FY)');
select is(rms_private.next_number('GS', '2026-03-31'), 'GS/2025-26/00001', 'earlier FY has its own counter');
select is(rms_private.next_number('GS', '2026-06-01'), 'GS/2026-27/00004', 'returning to an FY continues its counter');

-- FY token formats are configurable.
update public.number_series set fy_format = 'COMPACT' where code = 'GS';
select is(rms_private.next_number('GS', '2026-06-01'), 'GS/2627/00005', 'COMPACT FY format renders 2627');
update public.number_series set fy_format = 'SHORT' where code = 'GS';
select is(rms_private.next_number('GS', '2026-06-01'), 'GS/26-27/00006', 'SHORT FY format renders 26-27');

-- {PREFIX} token
select is(rms_private.next_number('TRANSFER', '2026-05-15'), 'TRF/2026-27/00001', '{PREFIX} token');

-- Monthly reset with {YYYY}{MM} and {YY}
insert into public.number_series (code, name, prefix, pattern, reset_policy)
values ('TEST_MONTHLY', 'Test monthly', 'T', '{PREFIX}-{YYYY}{MM}-{YY}-{SEQ:3}', 'MONTHLY');
select is(rms_private.next_number('TEST_MONTHLY', '2026-05-01'), 'T-202605-26-001', 'monthly: first');
select is(rms_private.next_number('TEST_MONTHLY', '2026-05-31'), 'T-202605-26-002', 'monthly: sequential');
select is(rms_private.next_number('TEST_MONTHLY', '2026-06-01'), 'T-202606-26-001', 'monthly: resets next month');

-- Never-reset series, admin start value, padding never truncates
insert into public.number_series (code, name, pattern, reset_policy, start_value)
values ('TEST_NEVER', 'Test never', 'N{SEQ:2}', 'NEVER', 99);
select is(rms_private.next_number('TEST_NEVER', '2026-05-01'), 'N99',  'start value honoured');
select is(rms_private.next_number('TEST_NEVER', '2030-01-01'), 'N100', 'value longer than padding is not truncated; NEVER does not reset');

-- Calendar-year FY (fy_start_month = 1)
insert into public.number_series (code, name, pattern, reset_policy, fy_start_month)
values ('TEST_CAL', 'Test calendar FY', 'C/{FY}/{SEQ}', 'YEARLY_FY', 1);
select is(rms_private.next_number('TEST_CAL', '2026-01-01'), 'C/2026/1', 'calendar-year FY renders a single year');

-- Errors
select throws_ok($$select rms_private.next_number('NO_SUCH_SERIES', '2026-05-01')$$,
                 'P0002', null, 'unknown series is rejected');
select throws_ok($$select rms_private.next_number('GS', null)$$,
                 '22004', null, 'a date is required');
update public.number_series set is_active = false where code = 'TEST_CAL';
select throws_ok($$select rms_private.next_number('TEST_CAL', '2026-05-01')$$,
                 '55000', null, 'inactive series is rejected');
select throws_ok($$insert into public.number_series (code, name, pattern) values ('BAD1','x','X/{FOO}/{SEQ}')$$,
                 '23514', null, 'unknown pattern token is rejected');
select throws_ok($$insert into public.number_series (code, name, pattern) values ('BAD2','x','X/{FY}')$$,
                 '23514', null, 'pattern without {SEQ} is rejected');

-- Counter row holds the last value
select is((select c.last_value from public.number_series_counters c
             join public.number_series s on s.id = c.series_id
            where s.code = 'GS' and c.period_key = 'FY2026'),
          6::bigint, 'counter stores the last issued value per period');

select * from finish();
rollback;
