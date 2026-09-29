with source as (
    select * from {{ ref('raw_audit_signature') }}
)

select
    sig_id,
    audit_seq,
    signer,
    meaning,
    to_timestamp(ts) as signed_at,
    signature
from source
