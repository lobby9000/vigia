package com.vigia.ingest.event;

import java.time.Clock;
import java.time.Instant;
import java.util.List;

import com.vigia.ingest.common.InvalidEventException;
import com.vigia.ingest.config.VigiaProperties;
import com.vigia.ingest.event.EventDtos.EventRequest;
import com.vigia.ingest.event.EventDtos.IngestResult;
import com.vigia.ingest.security.ApplicationPrincipal;

import org.springframework.stereotype.Service;

/**
 * Ingestion use case: check data quality, store the batch in PostgreSQL,
 * then archive the raw events in MongoDB.
 */
@Service
public class EventIngestionService {

    private final EventJdbcRepository events;
    private final RawEventArchive archive;
    private final Clock clock;
    private final VigiaProperties.Ingest limits;

    public EventIngestionService(EventJdbcRepository events, RawEventArchive archive, Clock clock,
            VigiaProperties properties) {
        this.events = events;
        this.archive = archive;
        this.clock = clock;
        this.limits = properties.ingest();
    }

    public IngestResult ingest(ApplicationPrincipal application, List<EventRequest> batch) {
        Instant receivedAt = clock.instant();
        rejectImplausibleTimestamps(batch, receivedAt);

        // 1) Source of truth, one transaction for the whole batch.
        events.insertBatch(application.applicationId(), batch, receivedAt);
        // 2) After the commit, outside the transaction: a slow MongoDB never holds database locks.
        archive.store(application.code(), batch, receivedAt);

        return new IngestResult(batch.size(), receivedAt);
    }

    /**
     * Bean Validation checks each field in isolation. Rules that depend on
     * "now" (a moving value) belong here, where the clock can be controlled.
     */
    private void rejectImplausibleTimestamps(List<EventRequest> batch, Instant now) {
        Instant oldest = now.minus(limits.maxEventAge());
        Instant newest = now.plus(limits.maxClockSkew());
        for (int i = 0; i < batch.size(); i++) {
            Instant occurredAt = batch.get(i).occurredAt();
            if (occurredAt.isBefore(oldest) || occurredAt.isAfter(newest)) {
                throw new InvalidEventException(i,
                        "occurredAt must be between %s and %s".formatted(oldest, newest));
            }
        }
    }
}
