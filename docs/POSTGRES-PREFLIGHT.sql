-- READ ONLY. Use on your DEVELOPMENT PostgreSQL database to identify staff
-- assignments that overlap once post-service buffers are accounted for.
-- Review results before considering any database exclusion constraint.
SELECT a.staff_id,
       a.reference AS first_reference,
       b.reference AS second_reference,
       a.starts_at AS first_start,
       b.starts_at AS second_start
FROM appointments AS a
JOIN appointments AS b
  ON a.staff_id = b.staff_id
 AND a.id < b.id
WHERE a.status IN ('confirmed', 'checked_in', 'at_risk')
  AND b.status IN ('confirmed', 'checked_in', 'at_risk')
  AND tstzrange(a.starts_at,
               a.ends_at + make_interval(mins => COALESCE(a.buffer_minutes,0)), '[)')
      && tstzrange(b.starts_at,
               b.ends_at + make_interval(mins => COALESCE(b.buffer_minutes,0)), '[)')
ORDER BY a.staff_id, a.starts_at;
