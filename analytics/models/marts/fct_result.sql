with results as (
    select * from {{ ref('stg_results') }}
),

experiments as (
    select * from {{ ref('stg_experiments') }}
)

select
    r.result_id,
    r.experiment_id,
    e.pipeline,
    r.result_name,
    r.content_sha256,
    r.attached_at
from results r
left join experiments e using (experiment_id)
