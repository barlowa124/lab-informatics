with experiments as (
    select * from {{ ref('stg_experiments') }}
),

audit as (
    select * from {{ ref('stg_audit_log') }}
    where entity = 'experiment'
),

signatures as (
    select
        a.entity_id as experiment_id,
        count(distinct s.sig_id) as signature_count
    from {{ ref('stg_audit_signature') }} s
    join {{ ref('stg_audit_log') }} a on s.audit_seq = a.seq
    group by all
),

durations as (
    select
        experiment_id,
        sum(seconds_in_state) as seconds_to_current_state,
        count(*) as transition_count
    from {{ ref('int_state_durations') }}
    group by all
)

select
    e.experiment_id,
    e.name,
    e.status,
    e.pipeline,
    coalesce(d.transition_count, 0) as transition_count,
    d.seconds_to_current_state,
    coalesce(s.signature_count, 0) as signature_count,
    (e.status = 'locked' and coalesce(s.signature_count, 0) > 0)
        as lock_signed
from experiments e
left join durations d using (experiment_id)
left join signatures s using (experiment_id)
