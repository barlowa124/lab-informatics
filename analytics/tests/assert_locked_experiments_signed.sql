-- A locked experiment must carry at least one e-signature. The LIMS
-- enforces the lock itself; this test catches a missing review step
-- on the signature side.
select experiment_id
from {{ ref('mart_experiment_audit') }}
where status = 'locked' and signature_count = 0
