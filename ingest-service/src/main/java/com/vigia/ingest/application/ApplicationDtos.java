package com.vigia.ingest.application;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

/**
 * Data Transfer Objects: the JSON contract of the applications endpoints.
 *
 * <p>Entities never leave the service layer. Exposing them directly would leak
 * internal fields (the API key hash), tie the public contract to the table
 * layout and trigger lazy loading during serialization.
 */
public final class ApplicationDtos {

    private ApplicationDtos() {
    }

    public record ApplicationResponse(
            String code,
            String name,
            String team,
            short tier,
            BigDecimal sloAvailability,
            int sloLatencyP95Ms,
            boolean active,
            OffsetDateTime createdAt) {

        static ApplicationResponse from(Application app) {
            return new ApplicationResponse(app.getCode(), app.getName(), app.getTeam().getName(), app.getTier(),
                    app.getSloAvailability(), app.getSloLatencyP95Ms(), app.isActive(), app.getCreatedAt());
        }
    }

    public record CreateApplicationRequest(
            @NotBlank
            @Pattern(regexp = "^[a-z0-9][a-z0-9-]{2,49}$", message = "use 3 to 50 lowercase letters, digits or dashes")
            String code,

            @NotBlank @Size(max = 120)
            String name,

            @NotBlank @Size(max = 80)
            String team,

            @NotNull @Min(1) @Max(3)
            Short tier,

            @NotNull
            @DecimalMin(value = "0.9", inclusive = false)
            @DecimalMax(value = "1.0", inclusive = false)
            BigDecimal sloAvailability,

            @NotNull @Positive
            Integer sloLatencyP95Ms) {
    }

    /** PATCH semantics: every field is optional, null means "leave as it is". */
    public record UpdateApplicationRequest(
            @DecimalMin(value = "0.9", inclusive = false)
            @DecimalMax(value = "1.0", inclusive = false)
            BigDecimal sloAvailability,

            @Positive
            Integer sloLatencyP95Ms,

            Boolean active) {
    }

    /** The plain API key travels exactly once, in this response. Only its hash is stored. */
    public record CreatedApplicationResponse(ApplicationResponse application, String apiKey, String warning) {
    }
}
