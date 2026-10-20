# Website availability

The public workflow checks the English and Chinese home/pricing pages and the
live billing catalog every five minutes. Each page must return HTTP 200 and real
EdgeSpeak HTML. English pricing allowances must match the live catalog. One
retry after 15 seconds filters isolated failures. No login or payment occurs.

`status.json` is a **transition record**, not a heartbeat: `changed_at` records
when the health state last changed, not the most recent successful check.
The workflow updates this file only when status changes. Its repository token
can write contents, but no external mail credentials are required. Pull requests
run tests only and cannot publish production status.

## Email alerts

Configure UptimeRobot free HTTP monitors for:

- https://edgespeak.com/
- https://edgespeak.com/zh
- https://edgespeak.com/pricing
- https://edgespeak.com/zh/pricing
- https://api.edgespeak.com/api/billing/catalog

Also configure a **keyword monitor** for:

https://raw.githubusercontent.com/lattifai/EdgeSpeak/main/monitoring/status.json

Require the keyword `"status": "up"` to be present. Assign the owner's verified
email contact to every monitor, with DOWN and UP notifications enabled. This
sixth monitor forwards Actions-detected content/catalog failures and recovery
through the same email notification service. Notification addresses belong in
the service configuration, not in this public repository.

Direct website monitors do not depend on Actions scheduling. GitHub schedules
can be delayed or dropped and are disabled after 60 days without repository
activity. The keyword monitor also has its own polling interval and GitHub raw
content may be cached; it is an extra business check, not the fastest outage
signal. A scheduled workflow that never runs cannot update the status file.

## Validation

```sh
node --test monitoring/check.test.mjs
node monitoring/check.mjs
```

Use workflow_dispatch for a live run. A nonzero result means confirmed website
failure or a failure to publish state; inspect the Actions log. To test email
notifications without taking production offline, use a temporary UptimeRobot
keyword monitor against the status file: require a deliberately absent test
keyword to trigger DOWN, then change it to the real healthy keyword for UP.
Verify both messages in the recipient inbox before considering delivery proven.
