package com.vigia.ingest.security;

/**
 * Who is calling the ingestion endpoint: the monitored application that owns
 * the API key. Controllers receive it with {@code @AuthenticationPrincipal}.
 */
public record ApplicationPrincipal(Integer applicationId, String code) {
}
