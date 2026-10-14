package com.vigia.ingest.application;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;

/**
 * Spring Data generates the implementation at startup: the SQL is derived from
 * the method names (findByCode becomes {@code ... WHERE code = ?}).
 *
 * <p>{@code @EntityGraph} loads the team in the same query (a JOIN). Without
 * it, listing N applications and reading each team name would run N extra
 * queries: the classic "N+1 queries" problem.
 */
public interface ApplicationRepository extends JpaRepository<Application, Integer> {

    @EntityGraph(attributePaths = "team")
    Optional<Application> findByCode(String code);

    @EntityGraph(attributePaths = "team")
    List<Application> findAllByOrderByTierAscCodeAsc();

    Optional<Application> findByApiKeyHashAndActiveTrue(String apiKeyHash);

    boolean existsByCode(String code);
}
