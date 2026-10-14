package com.vigia.ingest.common;

/** The requested resource does not exist. Mapped to HTTP 404 by {@link GlobalExceptionHandler}. */
public class NotFoundException extends RuntimeException {

    public NotFoundException(String message) {
        super(message);
    }

    public static NotFoundException application(String code) {
        return new NotFoundException("Application '%s' does not exist.".formatted(code));
    }
}
