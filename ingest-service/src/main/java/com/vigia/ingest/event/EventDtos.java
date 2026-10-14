package com.vigia.ingest.event;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;

/** JSON contract of POST /api/v1/events. */
public final class EventDtos {

    /** Bigger batches are cheaper per event, but must fit comfortably in one request. */
    public static final int MAX_BATCH_SIZE = 1000;

    private EventDtos() {
    }

    /**
     * One HTTP request observed by a monitored application.
     *
     * <p>{@code metadata} is free-form (app version, client, customer tier...):
     * it is not stored in PostgreSQL, whose schema is fixed, but archived as is
     * in MongoDB, which is schemaless.
     */
    public record EventRequest(
            @NotNull Instant occurredAt,
            @NotBlank @Size(max = 200) String endpoint,
            @NotNull @Pattern(regexp = "GET|POST|PUT|PATCH|DELETE") String method,
            @NotNull @Min(100) @Max(599) Integer statusCode,
            @NotNull @PositiveOrZero @Max(600_000) Integer latencyMs,
            @NotBlank @Size(max = 30) String region,
            Map<String, Object> metadata) {
    }

    /** {@code List<@Valid EventRequest>} makes Bean Validation check every element. */
    public record EventBatchRequest(
            @NotNull @Size(min = 1, max = MAX_BATCH_SIZE) List<@Valid @NotNull EventRequest> events) {
    }

    public record IngestResult(int accepted, Instant receivedAt) {
    }
}
