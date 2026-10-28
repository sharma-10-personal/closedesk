# Problem statement

A payments-operations analyst at a mid-size bank can't close the day's UPI reconciliation, because the settlement file, the core-banking ledger and the merchant records disagree on thousands of transactions, and she traces each one by hand across spreadsheets. If this worked, she'd start the day with a short list of true exceptions, each with a cause, the rupees at risk and a proposed fix she can approve in one click.

## Who

A payments-operations analyst at one **acquiring** bank (the merchant's bank), not NPCI and not the sender's bank.

## Why today's approach fails

She has three lists of the same day: NPCI settlement, her bank's ledger, and merchant/gateway records. They should agree. Timing skew, duplicates, amount differences, and failed-but-debited rows mean they don't. Spreadsheet matching does not finish in time, and leftover items are not ranked by money or deadline.

## What changes if this works

Matching runs in Exasol. Leftovers collapse into a few root causes. Each leftover has a proposed fix. She approves or rejects it. The books do not change without that click.
