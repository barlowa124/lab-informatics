-- The audit chain is hash-linked, but a deleted row leaves the chain
-- intact while breaking seq contiguity. Flag any gap.
with numbered as (
    select
        seq,
        seq - row_number() over (order by seq) as gap_key
    from {{ ref('stg_audit_log') }}
)

select seq
from numbered
where gap_key <> (select min(gap_key) from numbered)
