package com.vigia.ingest.config;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityScheme;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Metadata for the generated OpenAPI document (/v3/api-docs) and Swagger UI
 * (/swagger-ui.html). Endpoints and schemas are discovered automatically from
 * the controllers and DTOs; this only adds the title and the two auth schemes.
 */
@Configuration
public class OpenApiConfig {

    @Bean
    OpenAPI vigiaOpenApi() {
        return new OpenAPI()
                .info(new Info()
                        .title("Vigia Ingest Service")
                        .version("1.0.0")
                        .description("Receives request telemetry from monitored applications and manages "
                                + "their registration. Events use an X-API-Key; management uses a JWT "
                                + "issued by the analytics API."))
                .components(new Components()
                        .addSecuritySchemes("apiKey", new SecurityScheme()
                                .type(SecurityScheme.Type.APIKEY)
                                .in(SecurityScheme.In.HEADER)
                                .name("X-API-Key"))
                        .addSecuritySchemes("bearerAuth", new SecurityScheme()
                                .type(SecurityScheme.Type.HTTP)
                                .scheme("bearer")
                                .bearerFormat("JWT")));
    }
}
