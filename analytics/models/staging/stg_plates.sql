with source as (
    select * from {{ ref('raw_plates') }}
)

select
    experiment_id,
    plate,
    upper(well) as well,
    sample_id
from source
