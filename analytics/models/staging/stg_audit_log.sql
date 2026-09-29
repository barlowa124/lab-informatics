with source as (
    select * from {{ ref('raw_audit_log') }}
)

select
    seq,
    to_timestamp(ts) as logged_at,
    entity,
    entity_id,
    action,
    detail,
    json_extract_string(detail, '$.to') as transition_to,
    json_extract_string(detail, '$.from') as transition_from,
    hash,
    prev_hash
from source
