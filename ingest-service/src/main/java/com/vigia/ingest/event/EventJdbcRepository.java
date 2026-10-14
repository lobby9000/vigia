package com.vigia.ingest.event;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;

import com.vigia.ingest.event.EventDtos.EventRequest;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

/**
 * Writes events with plain JDBC instead of JPA.
 *
 * <p>JPA shines for rich domain objects that are read, changed and saved.
 * Telemetry is the opposite: thousands of immutable rows, written once.
 * A JDBC batch sends them in a few round trips and skips Hibernate's
 * persistence context, which would otherwise track every row in memory.
 */
@Repository
public class EventJdbcRepository {

    private static final String INSERT_SQL = """
            INSERT INTO request_events
                (app_id, occurred_at, received_at, endpoint, http_method, status_code, latency_ms, region)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """;

    private static final int JDBC_BATCH_SIZE = 500;

    private final JdbcTemplate jdbc;

    public EventJdbcRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** All rows commit together, or none does. */
    @Transactional
    public void insertBatch(int applicationId, List<EventRequest> events, Instant receivedAt) {
        OffsetDateTime received = OffsetDateTime.ofInstant(receivedAt, ZoneOffset.UTC);
        jdbc.batchUpdate(INSERT_SQL, events, JDBC_BATCH_SIZE, (statement, event) -> {
            statement.setInt(1, applicationId);
            statement.setObject(2, OffsetDateTime.ofInstant(event.occurredAt(), ZoneOffset.UTC));
            statement.setObject(3, received);
            statement.setString(4, event.endpoint());
            statement.setString(5, event.method());
            statement.setShort(6, event.statusCode().shortValue());
            statement.setInt(7, event.latencyMs());
            statement.setString(8, event.region());
        });
    }
}
