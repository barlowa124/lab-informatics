with source as (
    select * from {{ ref('raw_alarms') }}
)

select
    id as alarm_id,
    cast(ts as timestamptz) as fired_at,
    channel,
    rule,
    value
from source
