with readings as (
    select * from {{ ref('stg_readings') }}
)

select
    reading_id,
    captured_at,
    channel,
    value,
    unit,
    quality,
    (quality = 'ok') as value_usable
from readings
