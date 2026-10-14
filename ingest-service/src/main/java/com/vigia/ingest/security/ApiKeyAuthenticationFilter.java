package com.vigia.ingest.security;

import java.io.IOException;

import com.vigia.ingest.application.ApplicationRepository;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.AuthorityUtils;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Authenticates machine-to-machine calls with the {@code X-API-Key} header.
 *
 * <p>If the key belongs to an active application, the request continues as
 * that application with the {@code ROLE_INGEST} authority. Otherwise the
 * filter simply does nothing: the request stays anonymous and the
 * authorization rules in {@code SecurityConfig} answer 401.
 *
 * <p>This class is deliberately NOT a {@code @Component}: Spring Boot would
 * also register it as a global servlet filter, and it would run twice. It is
 * created inside {@code SecurityConfig} for the ingestion chain only.
 */
public class ApiKeyAuthenticationFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-API-Key";

    private final ApplicationRepository applications;

    public ApiKeyAuthenticationFilter(ApplicationRepository applications) {
        this.applications = applications;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String apiKey = request.getHeader(HEADER);
        if (apiKey != null && !apiKey.isBlank()) {
            applications.findByApiKeyHashAndActiveTrue(ApiKeys.hash(apiKey.strip()))
                    .ifPresent(app -> {
                        var principal = new ApplicationPrincipal(app.getId(), app.getCode());
                        var authentication = UsernamePasswordAuthenticationToken.authenticated(
                                principal, null, AuthorityUtils.createAuthorityList("ROLE_INGEST"));
                        SecurityContext context = SecurityContextHolder.createEmptyContext();
                        context.setAuthentication(authentication);
                        SecurityContextHolder.setContext(context);
                    });
        }
        chain.doFilter(request, response);
    }
}
