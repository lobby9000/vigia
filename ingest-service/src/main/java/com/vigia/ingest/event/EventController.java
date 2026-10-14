package com.vigia.ingest.event;

import com.vigia.ingest.event.EventDtos.EventBatchRequest;
import com.vigia.ingest.event.EventDtos.IngestResult;
import com.vigia.ingest.security.ApplicationPrincipal;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;

import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/events")
@Tag(name = "Events", description = "Telemetry ingestion for monitored applications")
@SecurityRequirement(name = "apiKey")
public class EventController {

    private final EventIngestionService service;

    public EventController(EventIngestionService service) {
        this.service = service;
    }

    /**
     * 202 Accepted rather than 201 Created: the contract promises that the
     * batch was accepted, not that it is already queryable. That leaves room to
     * put a queue (Kafka, SQS) behind this endpoint later without breaking
     * any client.
     */
    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    @Operation(summary = "Ingest a batch of 1 to 1000 request events for the calling application")
    public IngestResult ingest(@AuthenticationPrincipal ApplicationPrincipal application,
            @Valid @RequestBody EventBatchRequest batch) {
        return service.ingest(application, batch.events());
    }
}
