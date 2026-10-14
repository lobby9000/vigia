package com.vigia.ingest.security;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class ApiKeysTest {

    @Test
    void generatedKeysArePrefixedLongAndUnique() {
        String first = ApiKeys.generate();
        String second = ApiKeys.generate();

        assertThat(first).startsWith("vg_").hasSize(3 + 43); // 32 bytes -> 43 Base64 characters
        assertThat(first).isNotEqualTo(second);
    }

    @Test
    void hashIsIdenticalToTheOneComputedByPostgresql() {
        // Same value as encode(sha256(convert_to('dev-key-payments-api', 'UTF8')), 'hex')
        // in database/03_seed_reference.sql: Java and SQL must agree byte for byte.
        assertThat(ApiKeys.hash("dev-key-payments-api"))
                .isEqualTo("ab369b1118c1ebac9032e0b86c8124718b2c3d4ac2252eb704ddc427c893f5d9");
    }
}
