package com.vigia.ingest.common;

/** The request clashes with the current state (duplicate code...). Mapped to HTTP 409. */
public class ConflictException extends RuntimeException {

    public ConflictException(String message) {
        super(message);
    }
}
