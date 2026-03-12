package com.reviewer.config

import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

@Configuration
class Resilience4jConfig {
    @Bean
    fun circuitBreakerRegistry(): CircuitBreakerRegistry {
        return CircuitBreakerRegistry.ofDefaults()
    }
}
