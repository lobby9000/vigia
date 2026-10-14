package com.vigia.ingest.event;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.Optional;

import com.vigia.ingest.application.Application;
import com.vigia.ingest.application.ApplicationRepository;
import com.vigia.ingest.config.AppConfig;
import com.vigia.ingest.config.SecurityConfig;
import com.vigia.ingest.event.EventDtos.IngestResult;
import com.vigia.ingest.security.ApiKeys;
import com.vigia.ingest.security.ApplicationPrincipal;
import org.junit.jupiter.api.Test;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Slice test: only the web layer (controller, JSON, validation, security
 * filters) is started. The service and the repository are mocks, so no
 * database is needed.
 */
@WebMvcTest(controllers = EventController.class,
        properties = "vigia.security.jwt-secret=" + EventControllerTest.SECRET)
@Import({SecurityConfig.class, AppConfig.class})
class EventControllerTest {

    static final String SECRET = "test-secret-0123456789abcdef0123456789abcdef";

    private static final String VALID_BATCH = """
            {"events": [{
                "occurredAt": "2026-10-07T14:59:30Z",
                "endpoint": "/v1/payments",
                "method": "POST",
                "statusCode": 201,
                "latencyMs": 180,
                "region": "mx-central",
                "metadata": {"appVersion": "4.7.2", "client": "android"}
            }]}
            """;

    @Autowired
    private MockMvc mvc;

    @MockitoBean
    private EventIngestionService service;

    @MockitoBean
    private ApplicationRepository applications;

    @Test
    void requestsWithoutAnApiKeyAreRejected() throws Exception {
        mvc.perform(post("/api/v1/events").contentType(MediaType.APPLICATION_JSON).content(VALID_BATCH))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.status").value(401));
        verifyNoInteractions(service);
    }

    @Test
    void unknownApiKeysAreRejected() throws Exception {
        mvc.perform(post("/api/v1/events")
                        .header("X-API-Key", "vg_not-a-real-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(VALID_BATCH))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(service);
    }

    @Test
    void aValidBatchIsAcceptedOnBehalfOfTheKeyOwner() throws Exception {
        givenApiKeyOf(7, "payments-api", "dev-key-payments-api");
        when(service.ingest(any(), anyList())).thenReturn(new IngestResult(1, Instant.parse("2026-10-07T15:00:00Z")));

        mvc.perform(post("/api/v1/events")
                        .header("X-API-Key", "dev-key-payments-api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(VALID_BATCH))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.accepted").value(1));

        verify(service).ingest(eq(new ApplicationPrincipal(7, "payments-api")), argThat(events -> events.size() == 1));
    }

    @Test
    void invalidFieldsAreReportedWithTheirPath() throws Exception {
        givenApiKeyOf(7, "payments-api", "dev-key-payments-api");
        String badBatch = VALID_BATCH.replace("\"statusCode\": 201", "\"statusCode\": 700");

        mvc.perform(post("/api/v1/events")
                        .header("X-API-Key", "dev-key-payments-api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(badBatch))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.title").value("Validation failed"))
                .andExpect(jsonPath("$.errors['events[0].statusCode']").exists());
        verifyNoInteractions(service);
    }

    @Test
    void emptyBatchesAreRejected() throws Exception {
        givenApiKeyOf(7, "payments-api", "dev-key-payments-api");

        mvc.perform(post("/api/v1/events")
                        .header("X-API-Key", "dev-key-payments-api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"events\": []}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors.events").exists());
    }

    private void givenApiKeyOf(int id, String code, String apiKey) {
        Application application = mock(Application.class);
        when(application.getId()).thenReturn(id);
        when(application.getCode()).thenReturn(code);
        when(applications.findByApiKeyHashAndActiveTrue(ApiKeys.hash(apiKey))).thenReturn(Optional.of(application));
    }
}
