package com.vigia.ingest.config;

import java.nio.charset.StandardCharsets;
import java.util.Objects;

import javax.crypto.spec.SecretKeySpec;

import com.vigia.ingest.application.ApplicationRepository;
import com.vigia.ingest.security.ApiKeyAuthenticationFilter;
import com.vigia.ingest.security.ProblemAuthenticationEntryPoint;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;

/**
 * Two independent security filter chains, one per kind of client.
 *
 * <ol>
 *   <li>{@code /api/v1/events/**}: monitored applications (machines). They
 *       authenticate with a per-application API key.</li>
 *   <li>Everything else: people and tools holding a JWT issued by the
 *       analytics API. This service never issues tokens, it only validates
 *       them (an OAuth2 "resource server").</li>
 * </ol>
 *
 * <p>Both chains are stateless: no HTTP session, no cookies. That is also why
 * CSRF protection is off: CSRF abuses cookies the browser sends on its own,
 * and these clients send explicit headers instead.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    /** Name of the JWT claim that carries the user's role ("viewer" or "admin"). */
    public static final String ROLE_CLAIM = "role";

    private static final int MIN_SECRET_BYTES = 32; // HS256 requires a key of at least 256 bits

    @Bean
    @Order(1)
    SecurityFilterChain ingestionChain(HttpSecurity http, ApplicationRepository applications) throws Exception {
        http.securityMatcher("/api/v1/events/**")
                .csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .addFilterBefore(new ApiKeyAuthenticationFilter(applications), AnonymousAuthenticationFilter.class)
                .authorizeHttpRequests(auth -> auth.anyRequest().hasRole("INGEST"))
                .exceptionHandling(errors -> errors.authenticationEntryPoint(new ProblemAuthenticationEntryPoint()));
        return http.build();
    }

    @Bean
    @Order(2)
    SecurityFilterChain apiChain(HttpSecurity http) throws Exception {
        http.csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers("/actuator/health/**", "/actuator/info").permitAll()
                        .requestMatchers("/v3/api-docs/**", "/swagger-ui/**", "/swagger-ui.html").permitAll()
                        .requestMatchers(HttpMethod.GET, "/api/v1/applications/**").hasAnyRole("viewer", "admin")
                        .requestMatchers("/api/v1/applications/**").hasRole("admin")
                        .anyRequest().denyAll()) // deny by default: new endpoints are closed until a rule opens them
                .oauth2ResourceServer(oauth2 -> oauth2.jwt(jwt -> jwt.jwtAuthenticationConverter(jwtAuthenticationConverter())));
        return http.build();
    }

    /**
     * Validates HS256 tokens signed with the shared secret: signature, expiry
     * ({@code exp}, {@code nbf}) and issuer must all be correct.
     */
    @Bean
    JwtDecoder jwtDecoder(VigiaProperties properties) {
        String secret = Objects.requireNonNullElse(properties.security().jwtSecret(), "");
        byte[] key = secret.getBytes(StandardCharsets.UTF_8);
        if (key.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(
                    "vigia.security.jwt-secret (env JWT_SECRET) must have at least 32 characters. "
                            + "Generate one with: openssl rand -hex 32");
        }
        NimbusJwtDecoder decoder = NimbusJwtDecoder.withSecretKey(new SecretKeySpec(key, "HmacSHA256"))
                .macAlgorithm(MacAlgorithm.HS256)
                .build();
        decoder.setJwtValidator(JwtValidators.createDefaultWithIssuer(properties.security().jwtIssuer()));
        return decoder;
    }

    /** Maps the "role" claim to a Spring authority: role=admin becomes ROLE_admin. */
    public static JwtGrantedAuthoritiesConverter roleClaimConverter() {
        JwtGrantedAuthoritiesConverter roles = new JwtGrantedAuthoritiesConverter();
        roles.setAuthoritiesClaimName(ROLE_CLAIM);
        roles.setAuthorityPrefix("ROLE_");
        return roles;
    }

    static JwtAuthenticationConverter jwtAuthenticationConverter() {
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(roleClaimConverter());
        return converter;
    }
}
