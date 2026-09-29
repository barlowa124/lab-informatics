with source as (
    select * from {{ ref('raw_samples') }}
)

select
    sample_id,
    lower(kind) as kind,
    json_extract_string(meta, '$.tissue') as tissue,
    cast(json_extract_string(meta, '$.batch') as integer) as batch,
    to_timestamp(created) as registered_at
from source
