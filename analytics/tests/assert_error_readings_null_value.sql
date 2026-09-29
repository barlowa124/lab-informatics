-- Failed captures must carry a null value; usable readings must carry a
-- number. The capture service nulls value on device/transport errors, so
-- a mismatch means a bad reading would be averaged into channel stats.
select reading_id
from {{ ref('fct_reading') }}
where (quality = 'ok') != (value is not null)
