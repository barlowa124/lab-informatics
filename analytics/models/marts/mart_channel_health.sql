with readings as (
    select * from {{ ref('stg_readings') }}
),

alarms as (
    select channel, count(*) as alarm_count
    from {{ ref('stg_alarms') }}
    group by all
),

reading_stats as (
    select
        channel,
        min(unit) as unit,
        count(*) as reading_count,
        count(*) filter (quality = 'ok') as ok_count,
        count(*) filter (quality = 'transport-error')
            as transport_error_count,
        count(*) filter (quality = 'device-error') as device_error_count,
        round(100.0 * count(*) filter (quality = 'ok') / count(*), 1)
            as ok_pct,
        min(value) filter (quality = 'ok') as min_value,
        max(value) filter (quality = 'ok') as max_value,
        avg(value) filter (quality = 'ok') as mean_value
    from readings
    group by all
)

select
    r.channel,
    r.unit,
    r.reading_count,
    r.ok_count,
    r.transport_error_count,
    r.device_error_count,
    r.ok_pct,
    r.min_value,
    r.max_value,
    round(r.mean_value, 3) as mean_value,
    coalesce(a.alarm_count, 0) as alarm_count
from reading_stats r
left join alarms a using (channel)
order by r.channel
