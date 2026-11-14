-- Production audit Phase 2 (2026-11-14): every SECURITY DEFINER function pins its search_path, so
-- a definer function never resolves names through the caller's search_path (Supabase security
-- advisor "function_search_path_mutable"). The only function without it was the G-14 trigger
-- guard; all its references are schema-qualified, so an empty search_path is safe.
-- Fix forward: the original migration (20261105000200) is applied and is not edited (rule d).

alter function rms_private.credit_notes_g14_guard() set search_path = '';
