with source as (
    select * from {{ ref('raw_results') }}
)

select
    result_id,
    experiment_id,
    name as result_name,
    content_sha256,
    to_timestamp(created) as attached_at
from source
