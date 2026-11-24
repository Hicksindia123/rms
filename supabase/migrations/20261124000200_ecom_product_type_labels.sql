-- DEC-73 follow-up (user request 2026-11-24): the E-Commerce Gate Entry Product Type options read
-- "Our Product" / "Different Product". Only the label changes; logic keys off the stable codes
-- COMPANY_PRODUCT / DIFFERENT_PRODUCT (CLAUDE.md rule e). Returns already recorded keep their label
-- snapshot (G-18). Only the seeded label is replaced, so an admin relabel is never overwritten.

update public.option_items oi
   set label = 'Our Product',
       rule_text = 'Pick our product from the searchable product list'
  from public.option_sets os
 where os.id = oi.option_set_id
   and os.code = 'ECOM_PRODUCT_TYPE'
   and oi.code = 'COMPANY_PRODUCT'
   and oi.label = 'Company Product';

update public.option_items oi
   set rule_text = 'Enter the name of the item found in the packet'
  from public.option_sets os
 where os.id = oi.option_set_id
   and os.code = 'ECOM_PRODUCT_TYPE'
   and oi.code = 'DIFFERENT_PRODUCT'
   and oi.rule_text = 'Describe the item found in the packet';
