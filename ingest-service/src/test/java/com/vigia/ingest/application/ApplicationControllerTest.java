package com.vigia.ingest.application;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.Date;
import java.util.List;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.vigia.ingest.application.ApplicationDtos.ApplicationResponse;
import com.vigia.ingest.application.ApplicationDtos.CreatedApplicationResponse;
import com.vigia.ingest.config.AppConfig;
import com.vigia.ingest.config.SecurityConfig;
import com.vigia.ingest.common.NotFoundException;
import org.junit.jupiter.api.Test;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(controllers = ApplicationController.class,
        properties = "vigia.security.jwt-secret=" + ApplicationControllerTest.SECRET)
@Import({SecurityConfig.class, AppConfig.class})
class ApplicationControllerTest {

    static final String SECRET = "test-secret-0123456789abcdef0123456789abcdef";

    private static final ApplicationResponse PAYMENTS = new ApplicationResponse("payments-api", "Payments API",
            "Payments", (short) 1, new BigDecimal("0.99950"), 600, true, OffsetDateTime.parse("2026-10-01T00:00:00Z"));

    private static final String NEW_APP = """
            {"code": "fraud-api", "name": "Fraud API", "team": "Risk",
             "tier": 1, "sloAvailability": 0.999, "sloLatencyP95Ms": 300}
            """;

    @Autowired
    private MockMvc mvc;

    @MockitoBean
    private ApplicationService service;

    @MockitoBean
    private ApplicationRepository applications; // required by the API-key filter of the other chain

    @Test
    void readingRequiresAToken() throws Exception {
        mvc.perform(get("/api/v1/applications")).andExpect(status().isUnauthorized());
    }

    @Test
    void viewersCanRead() throws Exception {
        when(service.list()).thenReturn(List.of(PAYMENTS));

        mvc.perform(get("/api/v1/applications").with(jwt().authorities(new SimpleGrantedAuthority("ROLE_viewer"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].code").value("payments-api"))
                .andExpect(jsonPath("$[0].apiKeyHash").doesNotExist()); // DTOs never expose the hash
    }

    @Test
    void viewersCannotRegisterApplications() throws Exception {
        mvc.perform(post("/api/v1/applications")
                        .with(jwt().authorities(new SimpleGrantedAuthority("ROLE_viewer")))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(NEW_APP))
                .andExpect(status().isForbidden());
        verifyNoInteractions(service);
    }

    @Test
    void theRoleClaimDecidesTheAuthority() throws Exception {
        when(service.register(any())).thenReturn(new CreatedApplicationResponse(PAYMENTS, "vg_secret", "store it"));

        mvc.perform(post("/api/v1/applications")
                        .with(jwt().jwt(token -> token.claim(SecurityConfig.ROLE_CLAIM, "admin"))
                                .authorities(SecurityConfig.roleClaimConverter()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(NEW_APP))
                .andExpect(status().isCreated())
                .andExpect(header().string("Location", "http://localhost/api/v1/applications/payments-api"))
                .andExpect(jsonPath("$.apiKey").value("vg_secret"));
    }

    @Test
    void invalidRegistrationsAreRejectedBeforeReachingTheService() throws Exception {
        mvc.perform(post("/api/v1/applications")
                        .with(jwt().authorities(new SimpleGrantedAuthority("ROLE_admin")))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(NEW_APP.replace("fraud-api", "Fraud API!")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors.code").exists());
        verifyNoInteractions(service);
    }

    @Test
    void unknownApplicationsAre404() throws Exception {
        when(service.get("nope")).thenThrow(NotFoundException.application("nope"));

        mvc.perform(get("/api/v1/applications/nope").with(jwt().authorities(new SimpleGrantedAuthority("ROLE_viewer"))))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.detail").value("Application 'nope' does not exist."));
    }

    /**
     * End to end check of the real JwtDecoder: a token signed exactly like the
     * analytics API signs it (HS256, same secret, same issuer) is accepted, and
     * the same token with another issuer is refused.
     */
    @Test
    void acceptsTokensIssuedByTheAnalyticsApiOnly() throws Exception {
        when(service.list()).thenReturn(List.of(PAYMENTS));

        mvc.perform(get("/api/v1/applications").header("Authorization", "Bearer " + token("vigia-analytics", "viewer")))
                .andExpect(status().isOk());
        mvc.perform(get("/api/v1/applications").header("Authorization", "Bearer " + token("someone-else", "viewer")))
                .andExpect(status().isUnauthorized());
    }

    private static String token(String issuer, String role) throws Exception {
        JWTClaimsSet claims = new JWTClaimsSet.Builder()
                .subject("ana")
                .issuer(issuer)
                .claim(SecurityConfig.ROLE_CLAIM, role)
                .issueTime(new Date())
                .expirationTime(Date.from(Instant.now().plusSeconds(300)))
                .build();
        SignedJWT jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), claims);
        jwt.sign(new MACSigner(SECRET.getBytes(StandardCharsets.UTF_8)));
        return jwt.serialize();
    }
}
