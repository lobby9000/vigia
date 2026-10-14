package com.vigia.ingest.config;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Typed view of the {@code vigia.*} block in application.yml.
 *
 * <p>Records are immutable: Spring binds the values once through the
 * constructor at startup, and nobody can change them afterwards.
 */
@ConfigurationProperties(prefix = "vigia")
public record VigiaProperties(Security security, Ingest ingest) {

    /** JWT validation settings shared with the analytics API. */
    public record Security(String jwtSecret, String jwtIssuer) {
    }

    /** Data quality limits for incoming events. */
    public record Ingest(Duration maxEventAge, Duration maxClockSkew) {
    }
}
