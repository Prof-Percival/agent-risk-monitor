import logging

from . import db
from .config import Config
from .models import Analysis
from .rules import evaluate

log = logging.getLogger("analyzer")


def run_once(connection, config: Config) -> tuple[int, int]:
    """Returns how many events were looked at and how many alerts they produced."""
    with connection.cursor() as cursor:
        events = db.claim_pending(cursor, config.batch_size)

        if not events:
            connection.commit()
            return 0, 0

        alerts = 0

        for event in events:
            prior = 0
            if event.event_type == "file_read":
                prior = db.prior_sensitive_reads(
                    cursor, event, config.sensitive_read_window_minutes
                )

            findings = evaluate(
                Analysis(
                    event=event,
                    allowed_domains=config.allowed_domains,
                    prior_sensitive_reads=prior,
                )
            )

            if findings:
                db.write_findings(cursor, event, findings)
                alerts += len(findings)

                for finding in findings:
                    log.info(
                        "alert %s %s on %s: %s",
                        finding.severity,
                        finding.rule,
                        event.event_id,
                        finding.summary,
                    )

        db.mark_analyzed(cursor, [event.event_id for event in events])

    connection.commit()

    return len(events), alerts
