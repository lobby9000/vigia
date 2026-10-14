package com.vigia.ingest.event;

import java.time.Instant;
import java.util.Map;

import com.vigia.ingest.event.EventDtos.EventRequest;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.CompoundIndex;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

/**
 * The original event, metadata included, as a MongoDB document in the
 * {@code raw_events} collection. The analytics API aggregates these documents
 * to find which app version or region is failing.
 *
 * <p>Two indexes are declared here and created at startup:
 * <ul>
 *   <li>{@code app_time}: serves "events of app X since T" queries.</li>
 *   <li>a TTL index on {@code receivedAt}: MongoDB deletes each document
 *       7 days after it arrived. Retention without a cleanup job.</li>
 * </ul>
 */
@Document(collection = "raw_events")
@CompoundIndex(name = "app_time", def = "{'appCode': 1, 'occurredAt': -1}")
public class RawEventDocument {

    @Id
    private String id;
    private String appCode;
    private Instant occurredAt;
    @Indexed(name = "ttl_received_at", expireAfter = "7d")
    private Instant receivedAt;
    private String endpoint;
    private String method;
    private int statusCode;
    private int latencyMs;
    private String region;
    private Map<String, Object> metadata;

    protected RawEventDocument() {
        // for the MongoDB mapper
    }

    static RawEventDocument of(String appCode, EventRequest event, Instant receivedAt) {
        RawEventDocument document = new RawEventDocument();
        document.appCode = appCode;
        document.occurredAt = event.occurredAt();
        document.receivedAt = receivedAt;
        document.endpoint = event.endpoint();
        document.method = event.method();
        document.statusCode = event.statusCode();
        document.latencyMs = event.latencyMs();
        document.region = event.region();
        document.metadata = event.metadata() == null ? Map.of() : event.metadata();
        return document;
    }

    public String getId() {
        return id;
    }

    public String getAppCode() {
        return appCode;
    }

    public Instant getOccurredAt() {
        return occurredAt;
    }

    public Instant getReceivedAt() {
        return receivedAt;
    }

    public String getEndpoint() {
        return endpoint;
    }

    public String getMethod() {
        return method;
    }

    public int getStatusCode() {
        return statusCode;
    }

    public int getLatencyMs() {
        return latencyMs;
    }

    public String getRegion() {
        return region;
    }

    public Map<String, Object> getMetadata() {
        return metadata;
    }
}
