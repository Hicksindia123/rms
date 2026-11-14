-- P1-02 · 0006 — storage buckets (master plan §8.8, §9.6, DEC-04).
-- Private buckets have NO storage.objects policies for anon/authenticated: the backend issues
-- short-lived signed upload/download URLs with the service role. rms-branding is public-read
-- (public = true serves objects without policies); uploads go through the backend only.
-- Per-bucket size limits match the system_settings defaults (video 1 GB, documents 25 MB);
-- the backend enforces the configurable setting, the bucket limit is the hard ceiling.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('rms-videos',    'rms-videos',    false, 1073741824,
     array['video/mp4','video/quicktime']),
  ('rms-documents', 'rms-documents', false, 26214400,
     array['image/jpeg','image/png','application/pdf','image/heic','image/heif']),
  ('rms-branding',  'rms-branding',  true,  2097152,
     array['image/png','image/jpeg','image/svg+xml','image/x-icon','image/vnd.microsoft.icon','image/webp'])
on conflict (id) do update
  set public             = excluded.public,
      file_size_limit    = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;
