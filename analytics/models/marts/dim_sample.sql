with samples as (
    select * from {{ ref('stg_samples') }}
),

wells as (
    select * from {{ ref('stg_plates') }}
)

select
    s.sample_id,
    s.kind,
    s.tissue,
    s.batch,
    s.registered_at,
    count(w.well) as wells_assigned,
    count(distinct w.experiment_id) as experiments_used_in
from samples s
left join wells w using (sample_id)
group by all
