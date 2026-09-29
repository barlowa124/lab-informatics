with assignments as (
    select * from {{ ref('int_well_assignments') }}
)

select
    experiment_id || '-' || plate || '-' || well as well_assignment_id,
    experiment_id,
    plate,
    well,
    sample_id,
    sample_kind,
    tissue,
    batch,
    experiment_status,
    pipeline,
    row_number() over (
        partition by experiment_id, plate order by well
    ) as well_order
from assignments
