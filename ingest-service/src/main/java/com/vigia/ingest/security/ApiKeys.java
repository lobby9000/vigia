package com.vigia.ingest.security;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;

/**
 * Generation and hashing of ingestion API keys.
 *
 * <p>Only the SHA-256 hash of a key is stored. A fast hash is acceptable here
 * (unlike for passwords, which need a slow hash such as scrypt or bcrypt)
 * because the keys are 256 random bits: there is no dictionary to try, and
 * brute force over 2^256 values is impossible. A fast, deterministic hash also
 * lets the database find the owner of a key with a unique index lookup.
 */
public final class ApiKeys {

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final String PREFIX = "vg_"; // makes leaked keys easy to recognise in logs and scanners

    private ApiKeys() {
    }

    /** A new random key, for example {@code vg_3q2-...}: 32 bytes in URL-safe Base64. */
    public static String generate() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return PREFIX + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    /** Lowercase hex SHA-256, identical to PostgreSQL's encode(sha256(...), 'hex'). */
    public static String hash(String apiKey) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(apiKey.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("Every JDK ships SHA-256", e);
        }
    }
}
