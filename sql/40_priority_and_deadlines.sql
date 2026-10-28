-- Rank leftovers by rupees at risk and nearest deadline.
-- Compensation rupees-per-day is a config value, UNVERIFIED. Engine binds :rupees_per_day.

OPEN SCHEMA CLOSEDESK;

UPDATE breaks
SET rupees_at_risk = amount_inr
  + CASE
        WHEN deadline_ts IS NOT NULL AND deadline_ts < NOW()
        THEN :rupees_per_day * GREATEST(1, CEIL(SECONDS_BETWEEN(NOW(), deadline_ts) / 86400))
        ELSE 0
    END
WHERE run_id = :run_id;
