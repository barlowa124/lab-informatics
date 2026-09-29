with source as (
    select * from {{ ref('raw_readings') }}
)

select
    id as reading_id,
    cast(ts as timestamptz) as captured_at,
    channel,
    value,
    unit,
    quality
from source
