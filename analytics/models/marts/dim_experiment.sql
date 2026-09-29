with experiments as (
    select * from {{ ref('stg_experiments') }}
),

wells as (
    select * from {{ ref('stg_plates') }}
),

results as (
    select * from {{ ref('stg_results') }}
)

select
    e.experiment_id,
    e.name,
    e.status,
    e.pipeline,
    e.genome,
    e.created_at,
    count(distinct w.plate) as plates_used,
    count(w.well) as wells_assigned,
    count(distinct w.sample_id) as samples_used,
    count(distinct r.result_id) as results_attached
from experiments e
left join wells w using (experiment_id)
left join results r using (experiment_id)
group by all
