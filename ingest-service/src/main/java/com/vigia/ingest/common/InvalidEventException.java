package com.vigia.ingest.common;

/**
 * An event is well formed but unacceptable (for example its timestamp is a
 * week old). Mapped to HTTP 422 with the position of the offending event.
 */
public class InvalidEventException extends RuntimeException {

    private final int index;

    public InvalidEventException(int index, String reason) {
        super("events[%d]: %s".formatted(index, reason));
        this.index = index;
    }

    public int getIndex() {
        return index;
    }
}
