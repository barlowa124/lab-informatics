with alarms as (
    select * from {{ ref('stg_alarms') }}
),

readings as (
    select * from {{ ref('stg_readings') }}
)

select
    a.alarm_id,
    a.fired_at,
    a.channel,
    a.rule,
    a.value,
    r.reading_id
from alarms a
left join readings r
    on  r.channel = a.channel
    and r.captured_at = a.fired_at
    and r.value = a.value
