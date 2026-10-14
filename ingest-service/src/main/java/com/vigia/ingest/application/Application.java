package com.vigia.ingest.application;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;

/**
 * A monitored application (JPA entity over the {@code applications} table).
 *
 * <p>Encapsulation: there are no public setters for fields that must not
 * change freely. State changes go through methods that express intent
 * ({@link #updateObjectives}, {@link #setActive}).
 */
@Entity
@Table(name = "applications")
public class Application {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false, unique = true, length = 50)
    private String code;

    @Column(nullable = false, length = 120)
    private String name;

    // LAZY: the team row is only loaded when needed (queries that need it use an entity graph).
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "team_id", nullable = false)
    private Team team;

    @Column(nullable = false)
    private short tier;

    @Column(name = "slo_availability", nullable = false, precision = 6, scale = 5)
    private BigDecimal sloAvailability;

    @Column(name = "slo_latency_p95_ms", nullable = false)
    private int sloLatencyP95Ms;

    @Column(name = "api_key_hash", nullable = false, unique = true, length = 64)
    private String apiKeyHash;

    @Column(nullable = false)
    private boolean active = true;

    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    protected Application() {
    }

    public Application(String code, String name, Team team, short tier, BigDecimal sloAvailability,
            int sloLatencyP95Ms, String apiKeyHash) {
        this.code = code;
        this.name = name;
        this.team = team;
        this.tier = tier;
        this.sloAvailability = sloAvailability;
        this.sloLatencyP95Ms = sloLatencyP95Ms;
        this.apiKeyHash = apiKeyHash;
    }

    @PrePersist
    void onCreate() {
        if (createdAt == null) {
            createdAt = OffsetDateTime.now(ZoneOffset.UTC);
        }
    }

    /** Changes the service level objectives. A null argument keeps the current value. */
    public void updateObjectives(BigDecimal newAvailability, Integer newLatencyP95Ms) {
        if (newAvailability != null) {
            this.sloAvailability = newAvailability;
        }
        if (newLatencyP95Ms != null) {
            this.sloLatencyP95Ms = newLatencyP95Ms;
        }
    }

    /** Deactivated applications keep their history but their API key stops working. */
    public void setActive(boolean active) {
        this.active = active;
    }

    public Integer getId() {
        return id;
    }

    public String getCode() {
        return code;
    }

    public String getName() {
        return name;
    }

    public Team getTeam() {
        return team;
    }

    public short getTier() {
        return tier;
    }

    public BigDecimal getSloAvailability() {
        return sloAvailability;
    }

    public int getSloLatencyP95Ms() {
        return sloLatencyP95Ms;
    }

    public String getApiKeyHash() {
        return apiKeyHash;
    }

    public boolean isActive() {
        return active;
    }

    public OffsetDateTime getCreatedAt() {
        return createdAt;
    }
}
