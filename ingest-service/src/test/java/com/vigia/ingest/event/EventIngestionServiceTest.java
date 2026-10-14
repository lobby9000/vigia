package com.vigia.ingest.event;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.verifyNoInteractions;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import com.vigia.ingest.common.InvalidEventException;
import com.vigia.ingest.config.VigiaProperties;
import com.vigia.ingest.event.EventDtos.EventRequest;
import com.vigia.ingest.event.EventDtos.IngestResult;
import com.vigia.ingest.security.ApplicationPrincipal;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/** Plain unit test: no Spring context, collaborators are Mockito mocks, time is frozen. */
@ExtendWith(MockitoExtension.class)
class EventIngestionServiceTest {

    private static final Instant NOW = Instant.parse("2026-10-07T15:00:00Z");
    private static final ApplicationPrincipal PAYMENTS = new ApplicationPrincipal(7, "payments-api");

    @Mock
    private EventJdbcRepository events;

    @Mock
    private RawEventArchive archive;

    private EventIngestionService service;

    @BeforeEach
    void setUp() {
        var properties = new VigiaProperties(
                new VigiaProperties.Security("unused-in-this-test", "vigia-analytics"),
                new VigiaProperties.Ingest(Duration.ofDays(7), Duration.ofMinutes(5)));
        service = new EventIngestionService(events, archive, Clock.fixed(NOW, ZoneOffset.UTC), properties);
    }

    @Test
    void storesTheBatchFirstAndThenArchivesIt() {
        List<EventRequest> batch = List.of(event(NOW.minusSeconds(30)), event(NOW.minusSeconds(5)));

        IngestResult result = service.ingest(PAYMENTS, batch);

        assertThat(result.accepted()).isEqualTo(2);
        assertThat(result.receivedAt()).isEqualTo(NOW);
        InOrder order = inOrder(events, archive);
        order.verify(events).insertBatch(7, batch, NOW);
        order.verify(archive).store("payments-api", batch, NOW);
    }

    @Test
    void rejectsEventsFromTheFutureAndPointsAtTheCulprit() {
        List<EventRequest> batch = List.of(event(NOW), event(NOW.plus(Duration.ofMinutes(10))));

        assertThatThrownBy(() -> service.ingest(PAYMENTS, batch))
                .isInstanceOf(InvalidEventException.class)
                .hasMessageStartingWith("events[1]");
        verifyNoInteractions(events, archive); // nothing is stored when the batch is rejected
    }

    @Test
    void rejectsEventsOlderThanTheRetentionWindow() {
        List<EventRequest> batch = List.of(event(NOW.minus(Duration.ofDays(8))));

        assertThatThrownBy(() -> service.ingest(PAYMENTS, batch))
                .isInstanceOf(InvalidEventException.class)
                .hasMessageStartingWith("events[0]");
    }

    @Test
    void acceptsSmallClockSkew() {
        List<EventRequest> batch = List.of(event(NOW.plus(Duration.ofMinutes(4))));

        assertThat(service.ingest(PAYMENTS, batch).accepted()).isEqualTo(1);
    }

    static EventRequest event(Instant occurredAt) {
        return new EventRequest(occurredAt, "/v1/payments", "POST", 201, 120, "mx-central",
                Map.of("appVersion", "4.7.2"));
    }
}
