package com.vigia.ingest.application;

import java.util.List;

import com.vigia.ingest.application.ApplicationDtos.ApplicationResponse;
import com.vigia.ingest.application.ApplicationDtos.CreateApplicationRequest;
import com.vigia.ingest.application.ApplicationDtos.CreatedApplicationResponse;
import com.vigia.ingest.application.ApplicationDtos.UpdateApplicationRequest;
import com.vigia.ingest.common.ConflictException;
import com.vigia.ingest.common.NotFoundException;
import com.vigia.ingest.security.ApiKeys;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Business rules for monitored applications.
 *
 * <p>Dependencies arrive through the constructor (constructor injection):
 * the fields can be final, the class works without Spring in unit tests, and
 * a missing dependency fails at startup instead of at the first request.
 */
@Service
public class ApplicationService {

    private final ApplicationRepository applications;
    private final TeamRepository teams;

    public ApplicationService(ApplicationRepository applications, TeamRepository teams) {
        this.applications = applications;
        this.teams = teams;
    }

    @Transactional(readOnly = true)
    public List<ApplicationResponse> list() {
        return applications.findAllByOrderByTierAscCodeAsc().stream()
                .map(ApplicationResponse::from)
                .toList();
    }

    @Transactional(readOnly = true)
    public ApplicationResponse get(String code) {
        return applications.findByCode(code)
                .map(ApplicationResponse::from)
                .orElseThrow(() -> NotFoundException.application(code));
    }

    /**
     * Registers an application and returns its API key. The team is created
     * on the fly the first time it is mentioned.
     */
    @Transactional
    public CreatedApplicationResponse register(CreateApplicationRequest request) {
        if (applications.existsByCode(request.code())) {
            throw new ConflictException("Application '%s' already exists.".formatted(request.code()));
        }
        Team team = teams.findByName(request.team()).orElseGet(() -> teams.save(new Team(request.team())));
        String apiKey = ApiKeys.generate();
        Application saved = applications.save(new Application(
                request.code(), request.name(), team, request.tier(), request.sloAvailability(),
                request.sloLatencyP95Ms(), ApiKeys.hash(apiKey)));
        return new CreatedApplicationResponse(ApplicationResponse.from(saved), apiKey,
                "Store this key now: it cannot be shown again.");
    }

    /**
     * Partial update. No explicit save() is needed: the entity is "managed"
     * inside the transaction and Hibernate writes the changes at commit time
     * (dirty checking).
     */
    @Transactional
    public ApplicationResponse update(String code, UpdateApplicationRequest request) {
        Application app = applications.findByCode(code).orElseThrow(() -> NotFoundException.application(code));
        app.updateObjectives(request.sloAvailability(), request.sloLatencyP95Ms());
        if (request.active() != null) {
            app.setActive(request.active());
        }
        return ApplicationResponse.from(app);
    }
}
