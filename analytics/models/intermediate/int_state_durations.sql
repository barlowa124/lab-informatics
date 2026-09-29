with transitions as (
    select
        entity_id as experiment_id,
        transition_from as state,
        logged_at as entered_at,
        lead(logged_at) over (
            partition by entity_id order by logged_at
        ) as exited_at
    from {{ ref('stg_audit_log') }}
    where entity = 'experiment' and action = 'transition'
)

select
    experiment_id,
    state,
    entered_at,
    exited_at,
    epoch(exited_at - entered_at) as seconds_in_state
from transitions
where state is not null
