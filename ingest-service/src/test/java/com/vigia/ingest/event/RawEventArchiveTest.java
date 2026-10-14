package com.vigia.ingest.event;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;

import java.time.Instant;
import java.util.List;

import org.junit.jupiter.api.Test;

import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.data.mongodb.core.MongoOperations;

class RawEventArchiveTest {

    @Test
    void aMongoDbOutageNeverBreaksIngestion() {
        MongoOperations mongo = mock(MongoOperations.class);
        doThrow(new DataAccessResourceFailureException("MongoDB is down"))
                .when(mongo).insert(anyCollection(), eq(RawEventDocument.class));
        RawEventArchive archive = new RawEventArchive(mongo);
        Instant now = Instant.parse("2026-10-07T15:00:00Z");

        assertThatCode(() -> archive.store("payments-api", List.of(EventIngestionServiceTest.event(now)), now))
                .doesNotThrowAnyException();
    }
}
