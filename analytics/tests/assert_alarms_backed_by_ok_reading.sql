-- Every alarm must resolve to the 'ok' reading that breached its rule.
-- The capture service only evaluates rules on ok rows and persists both
-- records in the same write; a null or non-ok join means the alarm was
-- raised without evidence.
select a.alarm_id
from {{ ref('fct_alarm') }} a
left join {{ ref('fct_reading') }} r using (reading_id)
where r.reading_id is null or r.quality != 'ok'
