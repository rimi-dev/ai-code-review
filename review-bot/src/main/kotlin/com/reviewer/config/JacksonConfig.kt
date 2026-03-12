package com.reviewer.config

import tools.jackson.databind.DeserializationFeature
import tools.jackson.databind.ObjectMapper
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.json.JsonMapper
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.context.annotation.Primary

@Configuration
class JacksonConfig {

    @Bean("jacksonJsonMapper")
    @Primary
    fun objectMapper(): ObjectMapper {
        return JsonMapper.builder()
            .findAndAddModules()
            .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .disable(DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES)
            .build()
    }
}
