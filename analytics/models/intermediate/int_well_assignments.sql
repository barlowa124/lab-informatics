with wells as (
    select * from {{ ref('stg_plates') }}
),

samples as (
    select * from {{ ref('stg_samples') }}
),

experiments as (
    select * from {{ ref('stg_experiments') }}
)

select
    w.experiment_id,
    e.pipeline,
    e.status as experiment_status,
    w.plate,
    w.well,
    w.sample_id,
    s.kind as sample_kind,
    s.tissue,
    s.batch
from wells w
left join samples s using (sample_id)
left join experiments e using (experiment_id)
