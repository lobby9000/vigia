# Vigia ingest service: multi-stage build
# Stage 1 compiles with Maven; stage 2 only carries a JRE and the jar, so the
# final image has no compiler, no Maven and no source code.

FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
# Download dependencies in their own layer: cached until pom.xml changes.
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre
WORKDIR /app
RUN useradd --system --uid 10001 spring
COPY --from=build /src/target/ingest-service-1.0.0.jar app.jar
USER spring
EXPOSE 8080
# Size the heap from the container memory limit instead of the host's RAM.
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:+ExitOnOutOfMemoryError"
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
