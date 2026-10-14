package com.vigia.ingest.application;

import java.net.URI;
import java.util.List;

import com.vigia.ingest.application.ApplicationDtos.ApplicationResponse;
import com.vigia.ingest.application.ApplicationDtos.CreateApplicationRequest;
import com.vigia.ingest.application.ApplicationDtos.CreatedApplicationResponse;
import com.vigia.ingest.application.ApplicationDtos.UpdateApplicationRequest;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.support.ServletUriComponentsBuilder;

/**
 * HTTP layer only: translate requests into service calls and results into
 * responses. Authorization rules (viewer may read, admin may write) live in
 * SecurityConfig, validation rules on the DTOs, business rules in the service.
 */
@RestController
@RequestMapping("/api/v1/applications")
@Tag(name = "Applications", description = "Register monitored applications and manage their objectives")
@SecurityRequirement(name = "bearerAuth")
public class ApplicationController {

    private final ApplicationService service;

    public ApplicationController(ApplicationService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(summary = "List monitored applications (viewer or admin)")
    public List<ApplicationResponse> list() {
        return service.list();
    }

    @GetMapping("/{code}")
    @Operation(summary = "Get one application (viewer or admin)")
    public ApplicationResponse get(@PathVariable("code") String code) {
        return service.get(code);
    }

    @PostMapping
    @Operation(summary = "Register an application and obtain its API key (admin)")
    public ResponseEntity<CreatedApplicationResponse> register(@Valid @RequestBody CreateApplicationRequest request) {
        CreatedApplicationResponse created = service.register(request);
        URI location = ServletUriComponentsBuilder.fromCurrentRequest()
                .path("/{code}")
                .buildAndExpand(created.application().code())
                .toUri();
        return ResponseEntity.created(location).body(created); // 201 + Location header
    }

    @PatchMapping("/{code}")
    @Operation(summary = "Change objectives or deactivate an application (admin)")
    public ApplicationResponse update(@PathVariable("code") String code,
            @Valid @RequestBody UpdateApplicationRequest request) {
        return service.update(code, request);
    }
}
