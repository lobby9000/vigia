package com.vigia.ingest.config;

import java.time.Clock;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * General purpose beans.
 *
 * <p>The {@link Clock} is a bean instead of calling {@code Instant.now()}
 * directly so that tests can inject a fixed clock and check time rules
 * deterministically.
 */
@Configuration
@EnableConfigurationProperties(VigiaProperties.class)
public class AppConfig {

    @Bean
    Clock clock() {
        return Clock.systemUTC();
    }
}
