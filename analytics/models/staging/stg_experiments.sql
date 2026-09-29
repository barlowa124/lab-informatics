with source as (
    select * from {{ ref('raw_experiments') }}
)

select
    experiment_id,
    name,
    lower(status) as status,
    json_extract_string(meta, '$.pipeline') as pipeline,
    json_extract_string(meta, '$.genome') as genome,
    json_extract_string(meta, '$.lab') as lab,
    to_timestamp(created) as created_at
from source
