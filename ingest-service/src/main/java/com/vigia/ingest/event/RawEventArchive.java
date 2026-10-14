package com.vigia.ingest.event;

import java.time.Instant;
import java.util.List;

import com.vigia.ingest.event.EventDtos.EventRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.data.mongodb.core.MongoOperations;
import org.springframework.stereotype.Component;

/**
 * Best-effort archive of raw events in MongoDB.
 *
 * <p>PostgreSQL is the source of truth: if MongoDB is down, ingestion still
 * succeeds and only the diagnostic metadata of that batch is lost (and
 * logged). A production version would use the transactional outbox pattern to
 * guarantee both writes; see docs/architecture.md.
 */
@Component
public class RawEventArchive {

    private static final Logger log = LoggerFactory.getLogger(RawEventArchive.class);

    private final MongoOperations mongo;

    public RawEventArchive(MongoOperations mongo) {
        this.mongo = mongo;
    }

    public void store(String appCode, List<EventRequest> events, Instant receivedAt) {
        List<RawEventDocument> documents = events.stream()
                .map(event -> RawEventDocument.of(appCode, event, receivedAt))
                .toList();
        try {
            mongo.insert(documents, RawEventDocument.class); // one insertMany round trip
        } catch (RuntimeException e) {
            // Deliberately broad: whatever MongoDB says, the request must not fail because of it.
            log.warn("Could not archive {} raw events of {}: {}", documents.size(), appCode, e.getMessage());
        }
    }
}
