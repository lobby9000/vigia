package com.vigia.ingest;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Entry point. {@code @SpringBootApplication} turns on component scanning for
 * this package and its subpackages plus auto-configuration: Spring Boot sees
 * PostgreSQL, MongoDB, Spring Security and Spring MVC on the classpath and
 * wires them with the values in application.yml.
 */
@SpringBootApplication
public class IngestServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(IngestServiceApplication.class, args);
    }
}
